"""Thin client for the Instagram API with Instagram Login (graph.instagram.com)."""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger(__name__)


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, user_id: str, token: str, version: str = "v25.0", dry_run: bool = True):
        self.user_id = user_id
        self.token = token
        self.base = f"https://graph.instagram.com/{version}"
        self.dry_run = dry_run

    # ---------- low level ----------
    def _req(self, method: str, path: str, **params: Any) -> dict:
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        params["access_token"] = self.token
        if method == "GET":
            r = requests.get(url, params=params, timeout=30)
        else:
            r = requests.post(url, data=params, timeout=60)
        try:
            data = r.json()
        except ValueError:
            raise InstagramError(f"{method} {path}: HTTP {r.status_code} {r.text[:300]}")
        if r.status_code >= 400 or "error" in data:
            raise InstagramError(f"{method} {path}: {data.get('error', data)}")
        return data

    def _write(self, path: str, **params: Any) -> dict:
        if self.dry_run:
            log.info("[DRY_RUN] POST %s %s", path, {k: v for k, v in params.items()})
            return {"id": "dry-run"}
        return self._req("POST", path, **params)

    def _paged(self, path: str, limit_pages: int = 3, **params: Any) -> list[dict]:
        out: list[dict] = []
        data = self._req("GET", path, **params)
        for _ in range(limit_pages):
            out.extend(data.get("data", []))
            nxt = data.get("paging", {}).get("next")
            if not nxt:
                break
            r = requests.get(nxt, timeout=30)
            data = r.json()
        return out

    # ---------- account ----------
    def me(self) -> dict:
        return self._req("GET", "me", fields="user_id,username,name,account_type,followers_count,media_count")

    def refresh_token(self) -> dict:
        """Extend a long-lived token by 60 days (token must be >24h old)."""
        r = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": self.token},
            timeout=30,
        )
        data = r.json()
        if "access_token" not in data:
            raise InstagramError(f"refresh failed: {data}")
        return data

    # ---------- publishing ----------
    def _wait_container(self, container_id: str, timeout_s: int = 300) -> None:
        if self.dry_run:
            return
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self._req("GET", container_id, fields="status_code,status").get("status_code")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramError(f"container {container_id} status {status}")
            time.sleep(5)
        raise InstagramError(f"container {container_id} not ready after {timeout_s}s")

    def _container(self, url: str, is_video: bool, **extra: Any) -> str:
        params = dict(extra)
        if is_video:
            params.update(media_type="REELS", video_url=url)
        else:
            params["image_url"] = url
        cid = self._write(f"{self.user_id}/media", **params)["id"]
        self._wait_container(cid)
        return cid

    def publish(self, media_urls: list[str], caption: str, ai_generated: bool = False) -> str:
        """Publish a single image, a reel (single .mp4) or a carousel (2-10 items)."""
        if not media_urls:
            raise InstagramError("no media")
        flags = {"is_ai_generated": "true"} if ai_generated else {}
        is_video = [u.lower().endswith((".mp4", ".mov")) for u in media_urls]

        if len(media_urls) == 1:
            cid = self._container(media_urls[0], is_video[0], caption=caption, **flags)
        else:
            children = [
                self._container(u, v, is_carousel_item="true", **flags)
                for u, v in zip(media_urls[:10], is_video[:10])
            ]
            cid = self._write(
                f"{self.user_id}/media",
                media_type="CAROUSEL",
                children=",".join(children),
                caption=caption,
            )["id"]
            self._wait_container(cid)
        return self._write(f"{self.user_id}/media_publish", creation_id=cid)["id"]

    # ---------- comments ----------
    def recent_media(self, limit: int = 10) -> list[dict]:
        return self._req(
            "GET", f"{self.user_id}/media",
            fields="id,caption,timestamp,permalink,media_type", limit=limit,
        ).get("data", [])

    def comments(self, media_id: str) -> list[dict]:
        return self._paged(
            f"{media_id}/comments",
            fields="id,text,timestamp,username,from,replies{id,username,text}",
            limit=50,
        )

    def reply_comment(self, comment_id: str, text: str) -> dict:
        return self._write(f"{comment_id}/replies", message=text)

    def hide_comment(self, comment_id: str) -> dict:
        return self._write(comment_id, hide="true")

    # ---------- direct messages (needs instagram_business_manage_messages) ----------
    def conversations(self, limit: int = 20) -> list[dict]:
        return self._req(
            "GET", "me/conversations",
            platform="instagram", limit=limit,
            fields="id,updated_time,messages.limit(5){id,from,message,created_time}",
        ).get("data", [])

    def send_dm(self, recipient_id: str, text: str) -> dict:
        import json
        return self._write("me/messages", recipient=json.dumps({"id": recipient_id}),
                           message=json.dumps({"text": text}))

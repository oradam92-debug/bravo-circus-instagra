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
    def __init__(self, user_id: str, token: str, version: str = "v25.0", dry_run: bool = True,
                 host: str = "graph.facebook.com", page_id: str = ""):
        """host: graph.facebook.com (Facebook Login for Business / system-user token – the default
        for new Meta apps) or graph.instagram.com (legacy Instagram Login token)."""
        self.user_id = user_id
        self.token = token
        self.host = host
        self.base = f"https://{host}/{version}"
        self.dry_run = dry_run
        self.page_id = page_id  # Facebook Page linked to the IG account (needed for DMs on graph.facebook.com)
        self._page_token = ""

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
        if self.host == "graph.instagram.com":
            return self._req("GET", "me", fields="user_id,username,name,account_type,followers_count,media_count")
        return self._req("GET", self.user_id, fields="id,username,name,followers_count,media_count")

    def refresh_token(self) -> dict:
        """Extend a long-lived Instagram-Login token by 60 days (system-user tokens never expire)."""
        if self.host != "graph.instagram.com":
            return {"access_token": "", "expires_in": 0, "never_expires": True}
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

    def publish_story(self, media_url: str) -> str:
        """Publish an image or video as an Instagram Story."""
        is_video = media_url.lower().endswith((".mp4", ".mov"))
        params = {"media_type": "STORIES"}
        params["video_url" if is_video else "image_url"] = media_url
        cid = self._write(f"{self.user_id}/media", **params)["id"]
        self._wait_container(cid)
        return self._write(f"{self.user_id}/media_publish", creation_id=cid)["id"]

    def publish_facebook(self, media_urls: list[str], caption: str) -> str:
        """Cross-post to the linked Facebook Page (needs pages_manage_posts)."""
        node, tok = self._page()
        if self.dry_run:
            log.info("[DRY_RUN] FB post on %s: %s %s", node, media_urls, caption[:60])
            return "dry-run"
        url = media_urls[0]
        if url.lower().endswith((".mp4", ".mov")):
            r = requests.post(f"{self.base}/{node}/videos", timeout=300,
                              data={"file_url": url, "description": caption, "access_token": tok})
        elif len(media_urls) == 1:
            r = requests.post(f"{self.base}/{node}/photos", timeout=120,
                              data={"url": url, "message": caption, "access_token": tok})
        else:  # multi-photo post: upload unpublished photos, then attach them
            import json
            ids = []
            for u in media_urls[:10]:
                rr = requests.post(f"{self.base}/{node}/photos", timeout=120,
                                   data={"url": u, "published": "false", "access_token": tok}).json()
                if "id" in rr:
                    ids.append({"media_fbid": rr["id"]})
            r = requests.post(f"{self.base}/{node}/feed", timeout=120,
                              data={"message": caption, "attached_media": json.dumps(ids), "access_token": tok})
        data = r.json()
        if "error" in data:
            raise InstagramError(f"facebook post: {data['error']}")
        return data.get("post_id") or data.get("id", "")

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
    def _page(self) -> tuple[str, str]:
        """(node, token) used for messaging: 'me' on graph.instagram.com, the Page on graph.facebook.com."""
        if self.host == "graph.instagram.com":
            return "me", self.token
        if not self.page_id:
            raise InstagramError("FB_PAGE_ID is required for direct messages")
        if not self._page_token:
            self._page_token = self._req("GET", self.page_id, fields="access_token").get("access_token", self.token)
        return self.page_id, self._page_token

    def conversations(self, limit: int = 20) -> list[dict]:
        node, tok = self._page()
        r = requests.get(f"{self.base}/{node}/conversations", timeout=30, params={
            "platform": "instagram", "limit": limit, "access_token": tok,
            "fields": "id,updated_time,messages.limit(5){id,from,message,created_time}"})
        data = r.json()
        if "error" in data:
            raise InstagramError(f"conversations: {data['error']}")
        return data.get("data", [])

    def send_dm(self, recipient_id: str, text: str) -> dict:
        import json
        node, tok = self._page()
        if self.dry_run:
            log.info("[DRY_RUN] DM to %s: %s", recipient_id, text)
            return {"id": "dry-run"}
        r = requests.post(f"{self.base}/{node}/messages", timeout=30, data={
            "recipient": json.dumps({"id": recipient_id}), "message": json.dumps({"text": text}),
            "access_token": tok})
        data = r.json()
        if "error" in data:
            raise InstagramError(f"send_dm: {data['error']}")
        return data

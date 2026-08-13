"""AllAnime channel — free open GraphQL catalog + playable mp4 sources (backup).

Backup Resource Library v2 (docs/RESOURCE_BACKUP_PLAN.md §2.4):
- ``search``: POST https://api.mkissa.net/api (GraphQL) → standardized hits.
  AllAnime is a large free English anime catalog; the mkissa.net mirror is the
  current working API host (ani-cli PR #1779 migrated off the dead
  api.allanime.day 2026-07-22). Search carries sub/dub/raw episode counts.
- ``get_detail``: same GraphQL endpoint, ``show(_id:) { availableEpisodesDetail }``
  → 字幕 / 配音 / RAW 三个集数组。
- ``get_streams`` (verified playable 2026-08-13 via Clash 7892):
  episode source query needs an ``aaReq`` AES-256-GCM proof token. The
  per-epoch key is derived by bootstrapping the obfuscated mkissa
  client-crypto chunk — that derivation executes JS, so it runs in a tiny
  Node subprocess (``scripts/allanime_keygen``, documented exception §2.4).
  Decrypted sources: **Yt-mp4** (fast4speed.rsvp direct mp4, needs
  ``Referer: https://allanime.day/``) and **Mp4upload** (embed page → direct
  mp4, needs ``Referer: https://www.mp4upload.com/``). Both URLs are
  short-lived, so every ``get_streams`` re-derives/decrypts/resolves live.
- ``external_url``: https://mkissa.to/anime/{_id} (official watch page).

Chinese query → 0 edges (no noise, no short-circuit needed).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.models import (
    ChannelDetail,
    ChannelEpisode,
    ChannelEpisodeGroup,
    ChannelSearchResult,
    ChannelStream,
)
from app.services.channels import http
from app.services.channels.base import ChannelError, ChannelProvider

logger = logging.getLogger(__name__)

API_ENDPOINT = "https://api.mkissa.net/api"
WEB_BASE = "https://mkissa.to/anime"
ORIGIN = "https://mkissa.to"
SEARCH_LIMIT = 10
HEADERS = {
    "Content-Type": "application/json",
    "Referer": ORIGIN,
    "Origin": ORIGIN,
}

#: GraphQL search query (mirrors the Curd / ani-cli reference shape).
SEARCH_GQL = """\
query($search: SearchInput, $limit: Int, $page: Int, $translationType: VaildTranslationTypeEnumType, $countryOrigin: VaildCountryOriginEnumType) {
  shows(search: $search, limit: $limit, page: $page, translationType: $translationType, countryOrigin: $countryOrigin) {
    edges {
      _id
      name
      englishName
      availableEpisodes
      __typename
    }
  }
}
"""

#: Detail query — episode lists per translation lane (verified 2026-08-13).
DETAIL_GQL = """\
query($id: String!) {
  show(_id: $id) {
    _id
    name
    englishName
    availableEpisodesDetail
  }
}
"""

#: Episode-sources query. The ``show { _id name countryOfOrigin }`` fragment
#: is REQUIRED by the server (without it the API answers 500).
EPISODE_GQL = """\
query ($showId: String!, $translationType: VaildTranslationTypeEnumType!, $episodeString: String!) {
  episode(showId: $showId, translationType: $translationType, episodeString: $episodeString) {
    episodeString
    sourceUrls
    show { _id name countryOfOrigin }
  }
}
"""

#: Node keygen script (executes the obfuscated mkissa client-crypto chunk to
#: derive the per-epoch AES key + build id + lane; documented exception §2.4).
_KEYGEN_DIR = Path(__file__).resolve().parents[3] / "scripts" / "allanime_keygen"
_KEYGEN_SCRIPT = _KEYGEN_DIR / "keygen.cjs"
_KEYGEN_TIMEOUT = 60.0
#: How long a derived key is reused (server epoch rotates; keep it short).
_KEYGEN_TTL = 180.0
#: aaReq clock-bucket width (must match the server's 5-minute window).
_AA_WINDOW_MS = 300_000

#: Episode-ref encoding: ``{show_id}::{lane}::{episode_number}``.
_EPISODE_REF_RE = re.compile(r"^(.+)::(sub|dub|raw)::(\d+)$")

#: Hex-pair substitution table for source URLs (ani-cli provider_init cipher).
_SUBST = {
    "79": "A",
    "7a": "B",
    "7b": "C",
    "7c": "D",
    "7d": "E",
    "7e": "F",
    "7f": "G",
    "70": "H",
    "71": "I",
    "72": "J",
    "73": "K",
    "74": "L",
    "75": "M",
    "76": "N",
    "77": "O",
    "68": "P",
    "69": "Q",
    "6a": "R",
    "6b": "S",
    "6c": "T",
    "6d": "U",
    "6e": "V",
    "6f": "W",
    "60": "X",
    "61": "Y",
    "62": "Z",
    "59": "a",
    "5a": "b",
    "5b": "c",
    "5c": "d",
    "5d": "e",
    "5e": "f",
    "5f": "g",
    "50": "h",
    "51": "i",
    "52": "j",
    "53": "k",
    "54": "l",
    "55": "m",
    "56": "n",
    "57": "o",
    "48": "p",
    "49": "q",
    "4a": "r",
    "4b": "s",
    "4c": "t",
    "4d": "u",
    "4e": "v",
    "4f": "w",
    "40": "x",
    "41": "y",
    "42": "z",
    "08": "0",
    "09": "1",
    "0a": "2",
    "0b": "3",
    "0c": "4",
    "0d": "5",
    "0e": "6",
    "0f": "7",
    "00": "8",
    "01": "9",
    "15": "-",
    "16": ".",
    "67": "_",
    "46": "~",
    "02": ":",
    "17": "/",
    "07": "?",
    "1b": "#",
    "63": "[",
    "65": "]",
    "78": "@",
    "19": "!",
    "1c": "$",
    "1e": "&",
    "10": "(",
    "11": ")",
    "12": "*",
    "13": "+",
    "14": ",",
    "03": ";",
    "05": "=",
    "1d": "%",
}
_TOBEPARSED_RE = re.compile(r'"tobeparsed"\s*:\s*"([^"]*)"')
_MP4UPLOAD_VIDEO_RE = re.compile(r"(https?://[^\s\"'<>]+/video\.mp4)")

#: Lane labels surfaced in the UI.
_LANE_LABELS = {"sub": "字幕", "dub": "配音", "raw": "RAW"}

#: Which decrypted sources we can turn into playable mp4 streams.
_YT_MP4 = "Yt-mp4"
_MP4UPLOAD = "Mp4"


def _int_count(value) -> int:
    """Coerce an episode count from the GraphQL payload (int/float/str/None)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _decode_source_url(enc: str) -> str:
    """Decode a source URL using the hex-pair substitution table."""
    out = "".join(_SUBST.get(enc[i : i + 2], enc[i : i + 2]) for i in range(0, len(enc) - 1, 2))
    return out


def _aa_req(key_hex: str, epoch: str, build_id: str, lane: str, now_ms: int, qh: str) -> str:
    """Build the aaReq AES-256-GCM proof token (ani-cli PR #1772/#1779 shape)."""
    ts = (now_ms // _AA_WINDOW_MS) * _AA_WINDOW_MS
    payload = json.dumps(
        {"v": 1, "ts": ts, "epoch": int(epoch), "buildId": build_id, "qh": qh, "k": lane},
        separators=(",", ":"),
    ).encode()
    iv = hashlib.sha256(f"{epoch}:{build_id}:{qh}:{ts}:{lane}".encode()).digest()[:12]
    sealed = AESGCM(bytes.fromhex(key_hex)).encrypt(iv, payload, None)
    return base64.b64encode(b"\x01" + iv + sealed).decode()


def _decrypt_tobeparsed(key_hex: str, blob: str) -> dict:
    """Decrypt the ``tobeparsed`` blob → GraphQL response dict."""
    data = base64.b64decode(blob)
    if len(data) < 29:
        raise ChannelError("allanime", "streams", "tobeparsed blob too short", retryable=False)
    nonce, sealed = data[1:13], data[13:]
    plain = AESGCM(bytes.fromhex(key_hex)).decrypt(nonce, sealed, None)
    return json.loads(plain)


async def _run_keygen() -> dict[str, str]:
    """Derive KEY/EPOCH/BUILDID/LANE via the Node client-crypto bootstrap.

    This is the one documented Node subprocess in the codebase (§2.4): the
    mkissa key derivation executes obfuscated JS (SvelteKit client-crypto
    chunk), which is not feasible to port to Python. Fails loudly with a
    clear ChannelError when node/undici is unavailable.
    """
    if not _KEYGEN_SCRIPT.exists():
        raise ChannelError(
            "allanime",
            "streams",
            f"keygen script missing: {_KEYGEN_SCRIPT} (npm install in scripts/allanime_keygen?)",
            retryable=False,
        )
    env = {**os.environ}
    if proxy := env.get("AA_PROXY") or _proxy_from_settings():
        env["AA_PROXY"] = proxy
    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(_KEYGEN_SCRIPT),
            ORIGIN,
            "https://cdn.mkissa.net/all/mk/_app/immutable",
            cwd=str(_KEYGEN_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_KEYGEN_TIMEOUT)
    except (TimeoutError, FileNotFoundError) as exc:
        raise ChannelError("allanime", "streams", f"keygen failed: {exc}") from exc
    if proc.returncode != 0:
        raise ChannelError(
            "allanime",
            "streams",
            f"keygen exited {proc.returncode}: {stderr.decode(errors='replace')[:300]}",
        )
    out: dict[str, str] = {}
    for line in stdout.decode().splitlines():
        k, _, v = line.partition("=")
        if k and v:
            out[k] = v
    if not (out.get("KEY") and out.get("EPOCH") and out.get("BUILDID") and out.get("LANE")):
        raise ChannelError("allanime", "streams", f"keygen output incomplete: {stdout.decode()[:200]}")
    return out


def _proxy_from_settings() -> str:
    """Pull the configured HTTP proxy so keygen matches the app's network path."""
    try:
        from app.config import settings

        return settings.HTTP_PROXY
    except Exception:  # pragma: no cover - defensive
        return ""


#: Simple per-epoch key cache — avoids re-running the JS bootstrap for every
#: stream request while the epoch is stable.
_keygen_cache: dict = {"at": 0.0, "data": None}


async def _get_keys(force: bool = False) -> dict[str, str]:
    """Async keygen with TTL cache; ``force`` bypasses the cache (retry path)."""
    if not force:
        cached = _keygen_cache["data"]
        if cached and time.monotonic() - _keygen_cache["at"] < _KEYGEN_TTL:
            return cached
    data = await _run_keygen()
    _keygen_cache["at"] = time.monotonic()
    _keygen_cache["data"] = data
    return data


async def _fetch_sources(show_id: str, lane: str, ep: str) -> list[dict]:
    """Decrypt and return AllAnime source entries for one episode.

    Retries once with a fresh key after the first failure: the per-epoch key
    can rotate server-side between our cache window and the API call.
    """
    last_error: ChannelError | None = None
    for attempt in (0, 1):
        try:
            return await _fetch_sources_once(show_id, lane, ep, force=attempt == 1)
        except ChannelError as exc:
            last_error = exc
            if not exc.retryable or attempt == 1:
                raise
            logger.info("allanime stream fetch failed (retrying with fresh key): %s", exc)
    assert last_error is not None
    raise last_error


async def _fetch_sources_once(show_id: str, lane: str, ep: str, *, force: bool) -> list[dict]:
    keys = await _get_keys(force=force)
    qh = hashlib.sha256(EPISODE_GQL.encode()).hexdigest()
    now_ms = int(time.time() * 1000)
    aa = _aa_req(keys["KEY"], keys["EPOCH"], keys["BUILDID"], keys["LANE"], now_ms, qh)
    extensions = {
        "persistedQuery": {"version": 1, "sha256Hash": qh},
        "k": keys["LANE"],
        "aaReq": aa,
    }
    body = {
        "query": EPISODE_GQL,
        "variables": {
            "showId": show_id,
            "translationType": lane,
            "episodeString": ep,
        },
        "extensions": extensions,
    }
    headers = {**HEADERS, "x-build-id": keys["BUILDID"]}
    resp = await http.request("allanime", "streams", "POST", API_ENDPOINT, headers=headers, json_body=body)
    text = resp.text

    # Fast failure: the server returns an error list for invalid tokens/keys.
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("errors"):
        msg = str(payload["errors"])[:200]
        retryable = "crypto" in msg.lower() or "missing" in msg.lower() or "invalid" in msg.lower()
        raise ChannelError("allanime", "streams", f"graphql errors: {msg}", retryable=retryable)

    # Some responses carry plaintext sourceUrls; most carry tobeparsed.
    if isinstance(payload, dict):
        ep_data = ((payload.get("data") or {}).get("episode")) or {}
        if isinstance(ep_data.get("sourceUrls"), list) and ep_data["sourceUrls"]:
            return _normalize_sources(ep_data["sourceUrls"])

    m = _TOBEPARSED_RE.search(text)
    if not m:
        raise ChannelError(
            "allanime",
            "streams",
            f"no tobeparsed in response (len={len(text)}): {text[:200]}",
            retryable=True,
        )
    decrypted = _decrypt_tobeparsed(keys["KEY"], m.group(1))
    ep_data = ((decrypted.get("data") or {}).get("episode")) or decrypted.get("episode") or {}
    urls = ep_data.get("sourceUrls") or []
    if not isinstance(urls, list) or not urls:
        raise ChannelError("allanime", "streams", "no sourceUrls in decrypted payload", retryable=True)
    return _normalize_sources(urls)


def _normalize_sources(entries: list) -> list[dict]:
    out: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("sourceName") or "")
        raw = str(entry.get("sourceUrl") or "")
        if not name or not raw:
            continue
        # The API mixes two encodings: hex-pair-substituted URLs carry a
        # ``--`` prefix (ani-cli cipher), everything else is already plaintext.
        # Decoding plaintext with the table would corrupt digits/letters.
        url = _decode_source_url(raw[2:]) if raw.startswith("--") else raw
        try:
            priority = float(entry.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0.0
        out.append({"sourceName": name, "sourceUrl": url, "priority": priority})
    out.sort(key=lambda r: r["priority"], reverse=True)
    return out


async def _resolve_mp4upload(embed_url: str) -> str:
    """Extract the direct mp4 URL from an mp4upload embed page (real-time)."""
    resp = await http.request(
        "allanime",
        "streams",
        "GET",
        embed_url,
        headers={"Referer": "https://allanime.day/"},
    )
    m = _MP4UPLOAD_VIDEO_RE.search(resp.text)
    if not m:
        raise ChannelError("allanime", "streams", f"no video.mp4 on embed page: {embed_url}")
    return m.group(1).replace("&amp;", "&")


class AllAnimeChannel(ChannelProvider):
    """AllAnime — free open English catalog + playable mp4 backup."""

    id = "allanime"
    name = "AllAnime (mkissa)"
    language = "en"
    description = "开源 GraphQL 目录 + Yt-mp4/Mp4upload 直链（备选库）"
    supports_detail = True
    supports_streams = True
    external = False
    priority = 61

    @staticmethod
    def _edges(payload: dict) -> list:
        data = payload.get("data") if isinstance(payload, dict) else None
        shows = data.get("shows") if isinstance(data, dict) else None
        edges = shows.get("edges") if isinstance(shows, dict) else None
        if not isinstance(edges, list):
            raise ChannelError("allanime", "search", "unexpected payload shape", retryable=False)
        return edges

    async def search(self, keyword: str, page: int = 1) -> list[ChannelSearchResult]:
        variables = {
            "search": {
                "allowAdult": False,
                "allowUnknown": False,
                "query": keyword,
            },
            "limit": SEARCH_LIMIT,
            "page": page,
            "translationType": "sub",
            "countryOrigin": "ALL",
        }
        resp = await http.request(
            self.id,
            "search",
            "POST",
            API_ENDPOINT,
            headers=HEADERS,
            json_body={"variables": variables, "query": SEARCH_GQL},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "search", f"invalid json: {exc}") from exc

        edges = [e for e in self._edges(payload) if isinstance(e, dict)]
        # Main series (most episodes) first, like the GoAnime reference sort.
        edges.sort(
            key=lambda e: (
                _int_count((e.get("availableEpisodes") or {}).get("sub"))
                + _int_count((e.get("availableEpisodes") or {}).get("dub"))
            ),
            reverse=True,
        )

        out: list[ChannelSearchResult] = []
        for edge in edges:
            anime_id = str(edge.get("_id") or "")
            romaji = str(edge.get("name") or "").strip()
            english = str(edge.get("englishName") or "").strip()
            if not anime_id or not (romaji or english):
                continue
            episodes = edge.get("availableEpisodes") or {}
            sub = _int_count(episodes.get("sub"))
            dub = _int_count(episodes.get("dub"))
            raw = _int_count(episodes.get("raw"))
            display = english or romaji
            out.append(
                ChannelSearchResult(
                    channel=self.id,
                    title=display,
                    title_original=romaji if english else "",
                    cover_url="",
                    description="",
                    year="",
                    detail_ref=anime_id,
                    extra={
                        "sub_episodes": sub,
                        "dub_episodes": dub,
                        "raw_episodes": raw,
                        "total_episodes": sub + dub + raw,
                    },
                )
            )
        return out

    async def get_detail(self, detail_ref: str) -> ChannelDetail:
        resp = await http.request(
            self.id,
            "detail",
            "POST",
            API_ENDPOINT,
            headers=HEADERS,
            json_body={"variables": {"id": detail_ref}, "query": DETAIL_GQL},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise ChannelError(self.id, "detail", f"invalid json: {exc}") from exc
        if isinstance(payload, dict) and payload.get("errors"):
            raise ChannelError(
                self.id,
                "detail",
                f"graphql errors: {str(payload['errors'])[:200]}",
                retryable=False,
            )
        show = ((payload.get("data") or {}).get("show")) or {}
        if not isinstance(show, dict) or not show.get("_id"):
            raise ChannelError(self.id, "detail", "empty show payload", retryable=False)

        detail = show.get("availableEpisodesDetail") or {}
        groups: list[ChannelEpisodeGroup] = []
        for lane in ("sub", "dub", "raw"):
            raw_eps = detail.get(lane) or []
            eps = sorted({int(e) for e in raw_eps if str(e).isdigit()})
            if not eps:
                continue
            groups.append(
                ChannelEpisodeGroup(
                    title=_LANE_LABELS[lane],
                    episodes=[
                        ChannelEpisode(
                            title=f"第 {n} 集",
                            episode_ref=f"{detail_ref}::{lane}::{n}",
                        )
                        for n in eps
                    ],
                )
            )
        if not groups:
            raise ChannelError(self.id, "detail", "no episode groups", retryable=False)

        return ChannelDetail(
            channel=self.id,
            title=str(show.get("englishName") or show.get("name") or ""),
            cover_url="",
            description="",
            groups=groups,
        )

    async def get_streams(self, episode_ref: str) -> list[ChannelStream]:
        m = _EPISODE_REF_RE.match(episode_ref)
        if not m:
            raise ChannelError(self.id, "streams", f"malformed episode_ref: {episode_ref}", retryable=False)
        show_id, lane, ep = m.group(1), m.group(2), m.group(3)

        sources = await _fetch_sources(show_id, lane, ep)
        streams: list[ChannelStream] = []
        for source in sources:
            name = source["sourceName"]
            url = source["sourceUrl"]
            if name == _YT_MP4:
                streams.append(
                    ChannelStream(
                        type="mp4",
                        url=url,
                        quality="auto",
                        format="mp4",
                        headers={"Referer": "https://allanime.day/"},
                        note="AllAnime Yt-mp4",
                    )
                )
            elif name == _MP4UPLOAD:
                try:
                    direct = await _resolve_mp4upload(url)
                except ChannelError:
                    logger.warning("allanime mp4upload resolve failed: %s", url[:80])
                    continue
                streams.append(
                    ChannelStream(
                        type="mp4",
                        url=direct,
                        quality="auto",
                        format="mp4",
                        headers={"Referer": "https://www.mp4upload.com/"},
                        note="AllAnime Mp4upload",
                    )
                )
            if len(streams) >= 2:
                break
        if not streams:
            raise ChannelError(self.id, "streams", "no playable sources resolved", retryable=True)
        return streams

    def external_url(self, detail_ref: str) -> str:
        return f"{WEB_BASE}/{detail_ref}"

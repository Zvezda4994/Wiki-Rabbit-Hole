# rabbit.py  — Wiki Corkboard (One-note view)
# Fix: use a requests.Session with a real User-Agent so Wikipedia doesn't 403.

import random
import requests
import streamlit as st
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote
from time import sleep

WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
WIKI_BASE = "https://en.wikipedia.org"

# ---------- HTTP session (important!) ----------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "WikiCorkboard/1.0 (contact: your_email@example.com)",
    "Accept": "application/json, text/html;q=0.9"
})

def _get(url, tries=3, timeout=12):
    """Small helper with polite retry for rate limits."""
    for i in range(tries):
        r = SESSION.get(url, timeout=timeout)
        # Retry on 429/503; otherwise raise for other 4xx/5xx
        if r.status_code in (429, 503):
            sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r
    # Final attempt raise if still bad
    r.raise_for_status()
    return r

# -------------- Helpers --------------

def get_random_summary():
    # REST random summary
    r = _get(f"{WIKI_REST}/page/random/summary")
    return r.json()

def get_summary_by_title(title: str):
    r = _get(f"{WIKI_REST}/page/summary/{quote(title)}")
    # Some titles may 404 in the REST summary API; fall back to random.
    if r.status_code == 404:  # defensive; requests would have raised above normally
        return get_random_summary()
    return r.json()

def get_internal_links(title: str, max_links: int = 5):
    """Return up to max_links internal Wikipedia links from the page HTML."""
    html = _get(f"{WIKI_REST}/page/html/{quote(title)}")

    soup = BeautifulSoup(html.text, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]

        # Keep only internal content links like /wiki/Alan_Turing
        if not href.startswith("/wiki/"):
            continue

        # Filter namespaces like File:, Help:, Category:, Special:, Talk:, etc.
        tail = href.split("/wiki/")[-1]
        if ":" in tail:
            continue

        if href.startswith("/wiki/Main_Page"):
            continue

        text = a.get_text(strip=True)
        if not text or len(text) < 2:
            continue

        candidates.append(href)

    # Deduplicate while keeping randomness
    candidates = list(dict.fromkeys(candidates))
    random.shuffle(candidates)
    keep = candidates[: max_links * 3]  # over-sample then clean titles

    titles = []
    seen = set()
    for href in keep:
        # /wiki/Alan_Turing#Early_life → Alan_Turing
        t = unquote(href.split("/wiki/")[-1].split("#")[0])
        if t and t not in seen:
            seen.add(t)
            titles.append(t)
        if len(titles) >= max_links:
            break
    return titles

def note_from_summary(js):
    title = js.get("title", "Untitled")
    extract = js.get("extract", "(No summary available.)")
    url = js.get("content_urls", {}).get("desktop", {}).get("page", f"{WIKI_BASE}/wiki/{quote(title)}")
    return title, extract, url

# -------------- UI --------------

st.set_page_config(page_title="Wiki Corkboard", page_icon="🧶", layout="centered")

# light detective-board aesthetic via inline CSS
st.markdown(
    """
    <style>
    .note {
        background: #fff8d6;
        border: 2px solid #d6c98f;
        border-radius: 10px;
        padding: 18px 20px;
        box-shadow: 2px 4px 0 rgba(0,0,0,0.12);
        font-family: ui-serif, Georgia, 'Times New Roman', serif;
    }
    .title {
        font-size: 1.35rem; font-weight: 700; margin-bottom: 6px;
    }
    .extract {
        font-size: 1rem; line-height: 1.55; color: #333; margin-bottom: 10px;
    }
    .crumbs {
        font-size: .9rem; color: #555; margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧶 Wiki Corkboard (One-note view)")

if "stack" not in st.session_state:
    st.session_state.stack = []     # stack of titles visited (breadcrumb)
if "current" not in st.session_state:
    st.session_state.current = None # current article title

# Controls row
col1, col2, col3 = st.columns([1,1,2])
with col1:
    if st.button("🎲 Random start"):
        js = get_random_summary()
        title, extract, url = note_from_summary(js)
        st.session_state.current = title
        st.session_state.stack = [title]
        st.session_state.current_data = (title, extract, url)
        st.session_state.current_links = get_internal_links(title)

with col2:
    if st.button("↩️ Back", disabled=len(st.session_state.stack) <= 1):
        # pop current, show previous
        if len(st.session_state.stack) > 1:
            st.session_state.stack.pop()
            prev = st.session_state.stack[-1]
            js = get_summary_by_title(prev)
            t, ex, u = note_from_summary(js)
            st.session_state.current = t
            st.session_state.current_data = (t, ex, u)
            st.session_state.current_links = get_internal_links(t)

with col3:
    search_q = st.text_input("Jump to article (exact or close title)", placeholder="e.g., Alan Turing")

scol1, scol2 = st.columns([1,4])
with scol1:
    if st.button("🔎 Jump", disabled=not search_q.strip()):
        js = get_summary_by_title(search_q.strip())
        t, ex, u = note_from_summary(js)
        st.session_state.current = t
        st.session_state.stack.append(t)
        st.session_state.current_data = (t, ex, u)
        st.session_state.current_links = get_internal_links(t)

with scol2:
    if st.button("🧹 Reset"):
        st.session_state.stack = []
        st.session_state.current = None

# If no current, auto-start
if not st.session_state.get("current"):
    js = get_random_summary()
    title, extract, url = note_from_summary(js)
    st.session_state.current = title
    st.session_state.stack = [title]
    st.session_state.current_data = (title, extract, url)
    st.session_state.current_links = get_internal_links(title)

# Breadcrumbs
if st.session_state.stack:
    crumbs = "  ›  ".join(st.session_state.stack[-6:])
    st.markdown(f'<div class="crumbs">Path: {crumbs}</div>', unsafe_allow_html=True)

# Render the “note”
title, extract, url = st.session_state.current_data
with st.container():
    st.markdown('<div class="note">', unsafe_allow_html=True)
    st.markdown(f'<div class="title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="extract">{extract}</div>', unsafe_allow_html=True)
    st.markdown(f'[Open on Wikipedia]({url})', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.write("")  # spacer

# Link choices (5 random internal links)
st.subheader("Pick a lead:")
if not st.session_state.current_links:
    st.info("No links found on this page. Hit **Random start** or **Back**.")
else:
    cols = st.columns(5)
    for i, link_title in enumerate(st.session_state.current_links[:5]):
        with cols[i]:
            label = link_title[:22] + ("…" if len(link_title) > 22 else "")
            if st.button(label, key=f"link_{i}"):
                js2 = get_summary_by_title(link_title)
                t2, ex2, u2 = note_from_summary(js2)
                st.session_state.current = t2
                st.session_state.stack.append(t2)
                st.session_state.current_data = (t2, ex2, u2)
                st.session_state.current_links = get_internal_links(t2)

# Refresh choices (reshuffle links from current)
if st.button("Shuffle leads 🔀"):
    st.session_state.current_links = get_internal_links(st.session_state.current)

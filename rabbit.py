import random
import requests
import streamlit as st
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote
from html import escape
from time import sleep

WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
WIKI_BASE = "https://en.wikipedia.org"

SESSION = requests.Session()
SESSION.headers.update({ #default headers
    "User-Agent": "WikiCorkboard/1.1 (contact: your_email@example.com)",
    "Accept": "application/json, text/html;q=0.9"
})

def _get(url, tries=3, timeout=12): # helper to retry
    last_err = None
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After")
                if ra:
                    try:
                        sleep(float(ra))
                    except Exception:
                        sleep(1.5 * (i + 1))
                else:
                    sleep(1.5 * (i + 1))
                last_err = requests.HTTPError(f"{r.status_code} on {url}")
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_err = e
            sleep(0.5 * (i + 1))
    raise last_err if last_err else RuntimeError("Unknown HTTP error")

def get_random_summary(): # get a random article summary (JSON)
    r = _get(f"{WIKI_REST}/page/random/summary")
    return r.json()

def get_summary_by_title(title: str): # get article summary by specific title (JSON)
    r = _get(f"{WIKI_REST}/page/summary/{quote(title)}")
    return r.json()

def search_title_best(query: str): # search helper for fuzzy matches
    try:
        r = _get("https://en.wikipedia.org/w/api.php"
                 f"?action=opensearch&limit=1&format=json&search={quote(query)}")
        d = r.json()
        if d and d[1]:
            return d[1][0]
    except Exception:
        pass
    try:
        r = _get("https://en.wikipedia.org/w/api.php"
                 f"?action=query&list=search&srprop=&srlimit=1&format=json&srsearch={quote(query)}")
        d = r.json()
        hits = d.get("query", {}).get("search", [])
        if hits:
            return hits[0]["title"]
    except Exception:
        pass
    return None

def safe_get_summary(query_or_title: str): # wrapper with fallback
    try:
        return get_summary_by_title(query_or_title)
    except Exception:
        best = search_title_best(query_or_title)
        if not best:
            raise
        return get_summary_by_title(best)

def get_internal_links(title: str, max_links: int = 5): # get internal links from article given title
    try:
        html = _get(f"{WIKI_REST}/page/html/{quote(title)}")
        soup = BeautifulSoup(html.text, "html.parser")
        pairs = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            label = a.get_text(" ", strip=True)
            if not label or len(label) < 2:
                continue
            if "redlink=1" in href:
                continue
            if href.startswith("/wiki/"):
                tail = href.split("/wiki/", 1)[1]
            elif href.startswith("./"):
                tail = href[2:]
            else:
                continue
            tail = tail.split("#", 1)[0].split("?", 1)[0]
            if not tail:
                continue
            if ":" in tail:
                continue
            if tail == "Main_Page":
                continue
            decoded = unquote(tail)
            if decoded.replace("_", " ").lower() == title.replace("_", " ").lower():
                continue
            if "new" in (a.get("class") or []):
                continue
            nice = label.replace("_", " ").strip()
            if nice.lower() in {"edit", "citation needed", "help", "see also"}:
                continue
            if nice.isdigit():
                continue
            key = decoded.lower().replace("_", " ")
            if key not in seen:
                seen.add(key)
                pairs.append((decoded, nice))
            if len(pairs) >= max_links * 3:
                break
        random.shuffle(pairs)
        if pairs:
            return pairs[:max_links]
    except Exception:
        pass
    try:
        url = ("https://en.wikipedia.org/w/api.php"
               f"?action=parse&page={quote(title)}&prop=links&format=json")
        r = _get(url)
        data = r.json()
        links = data.get("parse", {}).get("links", [])
        titles = [l["*"] for l in links if l.get("ns") == 0 and l.get("*") and ("exists" in l)]
        titles = list(dict.fromkeys(titles))
        random.shuffle(titles)
        return [(t, t.replace("_", " ")) for t in titles[:max_links]]
    except Exception:
        return []

def note_from_summary(js): # extract title, extract, and URL from summary JSON
    title = js.get("title", "Untitled")
    extract = js.get("extract", "(No summary available.)")
    url = js.get("content_urls", {}).get("desktop", {}).get("page", f"{WIKI_BASE}/wiki/{quote(title)}")
    return title, extract, url

st.set_page_config(page_title="Wiki Corkboard", page_icon="🧶", layout="centered")

st.markdown(
    """
    <style>
    .note {
        display: block;
        width: 100%;
        background: #ffef9e;
        border: 2px solid #d6c98f;
        border-radius: 14px;
        padding: 20px 22px;
        box-shadow: 4px 6px 0 rgba(0,0,0,0.15);
        min-height: 180px;
        box-sizing: border-box;
        position: relative;
        overflow: hidden;
    }
    .note:before{
        content:"";
        position:absolute;
        inset:0;
        background: linear-gradient(transparent, rgba(0,0,0,0.03));
        pointer-events:none;
    }
    .title { font-size: 1.35rem; font-weight: 800; margin-bottom: 8px; }
    .extract { font-size: 1rem; line-height: 1.6; color: #2a2a2a; margin-bottom: 10px; }
    .crumbs { font-size: .9rem; color: #777; margin-bottom: 10px; }

    /* fixed-size buttons everywhere */
    .stButton > button {
        width: 100%;
        height: 72px;           /* fixed box height */
        text-align: center;
        white-space: normal;     /* allow wrapping */
        overflow: hidden;        /* clip overflow */
        text-overflow: ellipsis;
        line-height: 1.2;
        display: -webkit-box;    /* enable line clamp */
        -webkit-line-clamp: 3;   /* up to 3 lines then ellipsis */
        -webkit-box-orient: vertical;
    }

    .toolbar .stButton>button { width: 100%; height: 40px; }
    .main-actions .stButton>button { width: 100%; height: 40px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧶 Wiki Corkboard (One-note view)")

if "stack" not in st.session_state:
    st.session_state.stack = []
if "current" not in st.session_state:
    st.session_state.current = None

col1, col2, col3 = st.columns([1,1,2])

with col1:
    st.markdown('<div class="main-actions">', unsafe_allow_html=True)
    if st.button("🎲 Random start"):
        try:
            with st.spinner("Rolling the dice…"):
                js = get_random_summary()
                title, extract, url = note_from_summary(js)
                st.session_state.current = title
                st.session_state.stack = [title]
                st.session_state.current_data = (title, extract, url)
                st.session_state.current_links = get_internal_links(title)
        except Exception:
            st.error("Random fetch failed. Try again.")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="main-actions">', unsafe_allow_html=True)
    if st.button("↩️ Back", disabled=len(st.session_state.stack) <= 1):
        if len(st.session_state.stack) > 1:
            try:
                prev = st.session_state.stack[-2]
                with st.spinner("Going back…"):
                    js = safe_get_summary(prev)
                    t, ex, u = note_from_summary(js)
                    st.session_state.stack.pop()
                    st.session_state.current = t
                    st.session_state.current_data = (t, ex, u)
                    st.session_state.current_links = get_internal_links(t)
            except Exception:
                st.error("Couldn't go back.")
    st.markdown('</div>', unsafe_allow_html=True)

with col3:
    search_q = st.text_input("Jump to article (title or keywords)", placeholder="e.g., Alan Turing, apollo 11, elon")

scol1, scol2 = st.columns([1,4])
with scol1:
    st.markdown('<div class="toolbar">', unsafe_allow_html=True)
    if st.button("🔎 Jump", disabled=not search_q.strip()):
        try:
            with st.spinner("Searching…"):
                js = safe_get_summary(search_q.strip())
                t, ex, u = note_from_summary(js)
                st.session_state.current = t
                st.session_state.stack.append(t)
                if len(st.session_state.stack) > 200:
                    st.session_state.stack = st.session_state.stack[-200:]
                st.session_state.current_data = (t, ex, u)
                st.session_state.current_links = get_internal_links(t)
        except Exception:
            st.error("Couldn't find that article. Try a more exact title or different keywords.")
    st.markdown('</div>', unsafe_allow_html=True)

with scol2:
    st.markdown('<div class="toolbar">', unsafe_allow_html=True)
    if st.button("🧹 Reset"):
        st.session_state.stack = []
        st.session_state.current = None
    st.markdown('</div>', unsafe_allow_html=True)

if not st.session_state.get("current"):
    try:
        with st.spinner("Starting…"):
            js = get_random_summary()
            title, extract, url = note_from_summary(js)
            st.session_state.current = title
            st.session_state.stack = [title]
            st.session_state.current_data = (title, extract, url)
            st.session_state.current_links = get_internal_links(title)
    except Exception:
        st.error("Startup fetch failed. Hit Random start.")

if st.session_state.get("stack"):
    crumbs = "  ›  ".join(st.session_state.stack[-6:])
    st.markdown(f'<div class="crumbs">Path: {crumbs}</div>', unsafe_allow_html=True)

# unified yellow note block
title, extract, url = st.session_state.current_data
html_block = f'''
<div class="note">
    <div class="title">{escape(title)}</div>
    <div class="extract">{escape(extract)}</div>
    <a href="{escape(url, quote=True)}" target="_blank" rel="noopener">Open on Wikipedia</a>
</div>
'''
st.markdown(html_block, unsafe_allow_html=True)

st.write("")

st.subheader("Pick a lead:")
links = st.session_state.current_links
if not links:
    st.info("No links found on this page. Hit **Random start** or **Back**.")
else:
    items = links[:5]
    cols = st.columns(5, gap="large")  # 5 fixed, equal slots across

    for idx in range(5):
        with cols[idx]:
            if idx < len(items):
                next_title, nice_label = items[idx]
                label = (nice_label[:28] + "…") if len(nice_label) > 29 else nice_label
                if st.button(label, key=f"lead_{idx}"):
                    try:
                        with st.spinner("Following lead…"):
                            js2 = safe_get_summary(next_title)
                            t2, ex2, u2 = note_from_summary(js2)
                            st.session_state.current = t2
                            st.session_state.stack.append(t2)
                            if len(st.session_state.stack) > 200:
                                st.session_state.stack = st.session_state.stack[-200:]
                            st.session_state.current_data = (t2, ex2, u2)
                            st.session_state.current_links = get_internal_links(t2)
                    except Exception:
                        st.error("That lead fizzled. Try another.")
            else:
                st.write("")

if st.button("Shuffle leads 🔀"):
    try:
        with st.spinner("Shuffling…"):
            st.session_state.current_links = get_internal_links(st.session_state.current)
    except Exception:
        st.error("Shuffle failed. Try again.")

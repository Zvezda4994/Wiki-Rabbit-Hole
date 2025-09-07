# rabbit.py — Wiki Corkboard (One-note view)
# Streamlit app to hop Wikipedia like a detective corkboard.

import random
import requests
import streamlit as st
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote
from time import sleep

WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
WIKI_BASE = "https://en.wikipedia.org"

# Shared HTTP session
SESSION = requests.Session()
SESSION.headers.update({ #default headers
    "User-Agent": "WikiCorkboard/1.0 (contact: your_email@example.com)", # Identify yourself
    "Accept": "application/json, text/html;q=0.9" # JSON preferred, HTML for Parsoid
})

def _get(url, tries=3, timeout=12): # helper to retry
    """Tiny helper with polite retry for 429/503."""
    for i in range(tries):
        r = SESSION.get(url, timeout=timeout)
        if r.status_code in (429, 503):
            sleep(1.5 * (i + 1))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r # should not reach here

# Helpers

def get_random_summary(): # get a random article summary (JSON)
    r = _get(f"{WIKI_REST}/page/random/summary") # call through retrier method
    return r.json() # return parsed JSON

def get_summary_by_title(title: str): # get article summary by specific title (JSON)
    r = _get(f"{WIKI_REST}/page/summary/{quote(title)}")
    return r.json() # return parsed JSON to dict

def get_internal_links(title: str, max_links: int = 5): # get internal links from article given title
    """
    Return up to max_links internal links from the page as (target_title, nice_label) pairs.
    - Accept /wiki/... and ./... hrefs from Parsoid HTML
    - Strip fragments (#...) and query strings (?...)
    - Skip namespaces (File:, Help:, Category:, etc.), Main_Page, and self-links
    - If nothing found, fall back to Action API links that actually exist
    """
    # Attempt 1: REST HTML (Parsoid)
    try:
        html = _get(f"{WIKI_REST}/page/html/{quote(title)}") # fetch HTML version of the page
        soup = BeautifulSoup(html.text, "html.parser") # parse with BeautifulSoup 

        pairs = [] # for (title, label) pairs
        seen = set() # to avoid duplicates

        # Redlinks in Parsoid usually have class "new" and often use /w/index.php?...&redlink=1
        # but sometimes the href still looks like /wiki/Foo?redlink=1 — this strips querystrings either way.
        for a in soup.find_all("a", href=True): # iterate over all anchor tags with href
            href = a["href"].strip() # get link
            label = a.get_text(" ", strip=True) # get text 
            if not label or len(label) < 2: # skip empty or too short labels
                continue

            # Only consider /wiki/... and ./... links
            if href.startswith("/wiki/"):
                tail = href.split("/wiki/", 1)[1]
            elif href.startswith("./"):
                tail = href[2:]
            else:
                continue

            # Strip fragment and query
            tail = tail.split("#", 1)[0]
            tail = tail.split("?", 1)[0]
            if not tail: # nothing left, skip
                continue

            # Skip namespaces (File:, Help:, Category:, Special:, Talk:, Portal:, etc.)
            if ":" in tail:
                continue

            # Skip Main Page
            if tail == "Main_Page":
                continue

            decoded = unquote(tail) # decode URL-encoded parts

            # Skip self-links
            if decoded.replace("_", " ").lower() == title.replace("_", " ").lower():
                continue

            # If anchor has class "new" it's a redlink (missing page) — skip
            if "new" in (a.get("class") or []):
                continue

            # Clean the label
            nice = label.replace("_", " ").strip()
            if nice.lower() in {"edit", "citation needed", "help", "see also"}:
                continue

            if decoded not in seen: #check for duplicates
                seen.add(decoded) 
                pairs.append((decoded, nice)) # add to pairs

            if len(pairs) >= max_links * 3:  # oversample a bit
                break

        random.shuffle(pairs)
        if pairs:
            return pairs[:max_links]
    except Exception:
        pass  # fall through

    # Attempt 2: Action API fallback (only existing pages)
    try:
        url = ("https://en.wikipedia.org/w/api.php"
               f"?action=parse&page={quote(title)}&prop=links&format=json") # get links via Action API
        r = _get(url) # fetch with retrier helper
        data = r.json() # parse JSON
        links = data.get("parse", {}).get("links", []) # get links list
        # Keep only main-namespace links that EXIST (have the 'exists' flag)
        titles = [l["*"] for l in links if l.get("ns") == 0 and l.get("*") and ("exists" in l)] # filter for main namespace and existence
        titles = list(dict.fromkeys(titles)) # deduplicate while preserving order
        random.shuffle(titles) # just randomise
        # Label = title with spaces (good enough)
        return [(t, t.replace("_", " ")) for t in titles[:max_links]] # return up to max_links
    except Exception:
        return [] # no links available

def note_from_summary(js): # extract title, extract, and URL from summary JSON
    title = js.get("title", "Untitled") # get title
    extract = js.get("extract", "(No summary available.)") # get extract
    url = js.get("content_urls", {}).get("desktop", {}).get("page", f"{WIKI_BASE}/wiki/{quote(title)}") # get URL
    return title, extract, url # return all three in a tuple

#  UI 

st.set_page_config(page_title="Wiki Corkboard", page_icon="🧶", layout="centered")

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
    .title { font-size: 1.35rem; font-weight: 700; margin-bottom: 6px; }
    .extract { font-size: 1rem; line-height: 1.55; color: #333; margin-bottom: 10px; }
    .crumbs { font-size: .9rem; color: #bbb; margin-bottom: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧶 Wiki Corkboard (One-note view)")

if "stack" not in st.session_state:
    st.session_state.stack = []
if "current" not in st.session_state:
    st.session_state.current = None

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

# Render the note
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
links = st.session_state.current_links
if not links:
    st.info("No links found on this page. Hit **Random start** or **Back**.")
else:
    cols = st.columns(5)
    for i, (next_title, nice_label) in enumerate(links[:5]):
        label = (nice_label[:24] + "…") if len(nice_label) > 25 else nice_label
        with cols[i]:
            if st.button(label, key=f"link_{i}"):
                js2 = get_summary_by_title(next_title)
                t2, ex2, u2 = note_from_summary(js2)
                st.session_state.current = t2
                st.session_state.stack.append(t2)
                st.session_state.current_data = (t2, ex2, u2)
                st.session_state.current_links = get_internal_links(t2)

# Reshuffle
if st.button("Shuffle leads 🔀"):
    st.session_state.current_links = get_internal_links(st.session_state.current)

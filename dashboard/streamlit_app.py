#!/usr/bin/env python3
"""
Golden News Dashboard - Streamlit Version
Real-time news intelligence with 8 visualization tabs
"""
import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

# Page config - dark theme
st.set_page_config(
    page_title="Golden News Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Dark theme CSS
st.markdown("""
<style>
    .stApp { background-color: #0a0e17; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1a1f2e;
        border-radius: 6px 6px 0px 0px;
        padding: 10px 20px;
        color: #888;
    }
    .stTabs [data-baseweb="tab"]:hover { background-color: #252b3b; color: #e0e0e0; }
    .stTabs [aria-selected="true"] { background-color: #1a1f2e !important; color: #ffd700 !important; border-bottom: 2px solid #ffd700; }
    .signal-card { background: #1a1f2e; border-radius: 8px; padding: 14px; margin-bottom: 10px; border-left: 3px solid #888; }
    .signal-long { border-left-color: #00ff88; }
    .signal-short { border-left-color: #ff4757; }
    .signal-neutral { border-left-color: #888; }
    .stMetric { background: #1a1f2e; border-radius: 8px; padding: 15px; }
    .article-item { padding: 10px 0; border-bottom: 1px solid rgba(255,215,0,0.1); }
    div[data-testid="stMetricValue"] { color: #ffd700 !important; font-size: 28px !important; }
    div[data-testid="stMetricLabel"] { color: #888 !important; }
    .source-working { color: #00ff88; }
    .source-down { color: #ff4757; }
    .source-untested { color: #888; }
    section[data-testid="stSidebar"] { background-color: #0a0e17; }
    .heatmap-cell { height: 30px; text-align: center; line-height: 30px; border-radius: 4px; font-size: 11px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# Color scheme
COLORS = {
    "background": "#0a0e17",
    "card_bg": "#1a1f2e",
    "primary": "#ffd700",
    "accent": "#00d4ff",
    "positive": "#00ff88",
    "negative": "#ff4757",
    "neutral": "#888",
    "text": "#e0e0e0",
}

ASSET_COLORS = {
    "oil": "#ff6b35",
    "gold": "#ffd700",
    "stocks": "#00d4ff",
    "crypto": "#ff9500",
    "bonds": "#00ff88",
    "forex": "#bf5af2",
    "commodities": "#ff2d55",
    "multi": "#888",
}

# ==============================================================================
# DATABASE HELPERS
# ==============================================================================

def get_db():
    return sqlite3.connect(DB_PATH)

def get_latest_articles(limit=50):
    db = get_db()
    cursor = db.execute("""
        SELECT a.id, a.title, a.summary, a.url, a.source_id,
               a.published_at, a.fetched_at, a.sentiment_score,
               a.sentiment_label, a.is_trading_signal,
               s.display_name as source_name, s.category
        FROM news_articles a
        JOIN news_sources s ON a.source_id = s.id
        ORDER BY a.fetched_at DESC
        LIMIT ?
    """, (limit,))
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

def get_active_signals(limit=20):
    db = get_db()
    cursor = db.execute("""
        SELECT ts.*, a.title as article_title, a.url as article_url,
               s.display_name as source_name
        FROM trading_signals ts
        JOIN news_articles a ON ts.article_id = a.id
        JOIN news_sources s ON a.source_id = s.id
        WHERE ts.is_active = 1
        ORDER BY ts.generated_at DESC
        LIMIT ?
    """, (limit,))
    cols = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

def get_graph_data():
    """Build nodes and edges for D3.js force-directed graph"""
    articles = get_latest_articles(limit=40)
    signals = get_active_signals(limit=10)

    db = get_db()
    keyword_map = {}
    for art in articles:
        cursor = db.execute("""
            SELECT keyword FROM article_keywords
            WHERE article_id = ? LIMIT 10
        """, (art["id"],))
        keywords = [row[0] for row in cursor.fetchall()]

        text = f"{art['title']} {art.get('summary', '')}".lower()
        words = re.findall(r'\b\w{4,}\b', text)
        stop_words = {'that', 'this', 'with', 'from', 'have', 'been', 'were', 'they',
                      'what', 'when', 'where', 'which', 'about', 'would', 'could',
                      'from', 'their', 'there', 'being', 'after', 'more', 'also',
                      'just', 'very', 'will', 'would', 'could', 'should', 'about',
                      'over', 'such', 'into', 'only', 'other', 'then', 'than', 'both'}
        keyword_set = set(w for w in words if w not in stop_words)
        keywords.extend(list(keyword_set)[:5])
        keyword_map[art["id"]] = list(set(keywords))

    db.close()

    nodes = []
    for art in articles:
        signal_colors = [s["asset_class"] for s in signals if s["article_id"] == art["id"]]
        asset_class = signal_colors[0] if signal_colors else art["category"]

        sentiment = art.get("sentiment_label", "neutral")
        node_color = {
            "positive": COLORS["positive"],
            "negative": COLORS["negative"],
            "neutral": COLORS["neutral"]
        }.get(sentiment, COLORS["neutral"])

        nodes.append({
            "id": art["id"],
            "title": art["title"][:60] + "..." if len(art["title"]) > 60 else art["title"],
            "full_title": art["title"],
            "url": art["url"],
            "source": art["source_name"],
            "published": art["published_at"],
            "sentiment": sentiment,
            "asset_class": asset_class,
            "color": node_color,
            "size": 16 if art.get("is_trading_signal") else 8,
            "is_signal": art.get("is_trading_signal", 0) == 1,
            "keywords": list(set(keyword_map.get(art["id"], [])))
        })

    edges = []
    for i, art_a in enumerate(articles):
        for art_b in articles[i+1:]:
            kw_a = set(keyword_map.get(art_a["id"], []))
            kw_b = set(keyword_map.get(art_b["id"], []))
            shared = kw_a & kw_b

            if len(shared) >= 3:
                strength = 0.3 + (0.2 * len(shared))
                if art_a["source_name"] == art_b["source_name"]:
                    strength += 0.3

                edges.append({
                    "source": art_a["id"],
                    "target": art_b["id"],
                    "strength": min(strength, 1.0),
                    "shared_keywords": list(shared)[:5]
                })

    return {"nodes": nodes, "edges": edges, "signals": signals}

def get_sources():
    db = get_db()
    cursor = db.execute("""
        SELECT id, name, display_name, category, api_type,
               is_active, is_working, last_tested_at, last_response_time_ms,
               rate_limit_rpm, monthly_cost_usd, description
        FROM news_sources
        ORDER BY display_name
    """)
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

def get_market_prices(limit=50):
    db = get_db()
    cursor = db.execute("""
        SELECT id, symbol, price, change_pct, volume, source, fetched_at
        FROM market_prices
        ORDER BY fetched_at DESC
        LIMIT ?
    """, (limit,))
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    db.close()
    return [dict(zip(cols, row)) for row in rows]

# ==============================================================================
# D3.JS GRAPH HTML
# ==============================================================================

def get_d3_graph_html():
    """Returns self-contained D3.js force-directed graph HTML"""
    return r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0e17; overflow: hidden; font-family: Inter, sans-serif; }
        #graph { width: 100vw; height: 100vh; display: block; }
        #tooltip {
            position: absolute; background: #1a1f2e; border: 1px solid #ffd700;
            border-radius: 8px; padding: 12px; font-size: 12px; max-width: 340px;
            pointer-events: none; opacity: 0; z-index: 100;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }
        #tooltip .tt-title { color: #e0e0e0; font-weight: 600; font-size: 12px; }
        #tooltip .tt-meta { font-size: 10px; color: #888; margin-top: 6px; }
        #tooltip .tt-keywords { font-size: 10px; color: #00d4ff; margin-top: 4px; }
        #stats {
            position: absolute; bottom: 20px; right: 20px;
            color: #888; font-size: 11px; font-family: Inter, sans-serif;
        }
        #legend {
            position: absolute; bottom: 20px; left: 20px;
            background: rgba(26,31,46,0.95); border-radius: 8px;
            padding: 12px 16px; font-size: 10px; border: 1px solid rgba(255,215,0,0.15);
        }
        #legend .leg-title { color: #ffd700; font-weight: 600; margin-bottom: 8px; }
        #legend .leg-item { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; color: #e0e0e0; }
        #legend .leg-dot { width: 10px; height: 10px; border-radius: 50%; }
        #controls {
            position: absolute; top: 16px; left: 16px;
            background: rgba(26,31,46,0.95); border-radius: 8px;
            padding: 12px 16px; font-size: 11px; border: 1px solid rgba(255,215,0,0.2);
            display: flex; gap: 8px; align-items: center;
        }
        #controls label { color: #ffd700; font-weight: 600; }
        #controls input[type=range] { width: 100px; accent-color: #ffd700; }
        #controls button {
            background: rgba(255,215,0,0.15); border: 1px solid rgba(255,215,0,0.4);
            color: #ffd700; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 10px;
        }
        #controls button:hover { background: rgba(255,215,0,0.3); }
        .node-label { pointer-events: none; font-family: Inter, sans-serif; fill: #e0e0e0; font-size: 8px; }
    </style>
</head>
<body>
    <svg id="graph"></svg>
    <div id="tooltip">
        <div class="tt-title"></div>
        <div class="tt-meta"></div>
        <div class="tt-keywords"></div>
    </div>
    <div id="controls">
        <label>Nodes:</label>
        <input type="range" id="nodeSlider" min="5" max="40" value="15">
        <span id="nodeCount">15</span>
        <button id="resetBtn">Reset</button>
        <button id="labelsBtn">Labels</button>
    </div>
    <div id="legend">
        <div class="leg-title">Sentiment</div>
        <div class="leg-item"><div class="leg-dot" style="background:#00ff88"></div> Positive</div>
        <div class="leg-item"><div class="leg-dot" style="background:#ff4757"></div> Negative</div>
        <div class="leg-item"><div class="leg-dot" style="background:#888"></div> Neutral</div>
        <div class="leg-item"><div class="leg-dot" style="background:transparent;border:2px solid #ffd700;border-radius:50%"></div> Signal</div>
    </div>
    <div id="stats"></div>

    <script>
    const containerId = 'graph';
    const container = document.getElementById(containerId);
    const tooltip = document.getElementById('tooltip');

    let width = window.innerWidth;
    let height = window.innerHeight;

    const svg = d3.select('#graph')
        .attr('width', width)
        .attr('height', height)
        .style('background', '#0a0e17');

    const g = svg.append('g');

    // Zoom
    const zoom = d3.zoom().scaleExtent([0.2, 4]).on('zoom', e => g.attr('transform', e.transform));
    svg.call(zoom);

    // Controls
    let showLabels = true;
    let nodeLimit = 15;
    let sim, link, node, nodesData, linksData;

    document.getElementById('nodeSlider').addEventListener('input', function() {
        nodeLimit = +this.value;
        document.getElementById('nodeCount').textContent = nodeLimit;
        svg.selectAll('.node-group').style('display', (d, i) => i < nodeLimit ? 'block' : 'none');
    });

    document.getElementById('resetBtn').onclick = () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
    document.getElementById('labelsBtn').onclick = () => {
        showLabels = !showLabels;
        svg.selectAll('.node-label').style('opacity', showLabels ? 1 : 0);
    };

    // Center force
    const centerForce = d3.forceCenter(width / 2, height / 2);

    // Stats text
    const statsText = svg.append('text')
        .attr('x', width - 20).attr('y', height - 20)
        .attr('text-anchor', 'end').attr('fill', '#888').attr('font-size', '11px')
        .attr('font-family', 'Inter, sans-serif')
        .text('Loading graph data...');

    function renderGraph(data) {
        if (!data.nodes || data.nodes.length === 0) {
            svg.append('text').attr('x', width/2).attr('y', height/2)
                .attr('text-anchor', 'middle').attr('fill', '#888').attr('font-family', 'Inter, sans-serif')
                .text('No articles yet. Run collector.py to fetch news.');
            return;
        }

        statsText.text(`${data.nodes.length} articles | ${data.edges ? data.edges.length : 0} connections`);

        const nodes = data.nodes.map(n => ({
            ...n,
            x: width/2 + (Math.random() - 0.5) * Math.min(width * 0.4, 400),
            y: height/2 + (Math.random() - 0.5) * Math.min(height * 0.4, 300)
        }));

        const nodeMap = new Map(nodes.map(n => [n.id, n]));
        nodesData = nodes;

        const links = (data.edges || []).map(e => ({
            source: nodeMap.get(e.source),
            target: nodeMap.get(e.target),
            strength: e.strength,
            shared: e.shared_keywords || []
        })).filter(e => e.source && e.target);

        linksData = links;

        // Clear previous
        g.selectAll('*').remove();

        // Links
        link = g.append('g').attr('class', 'links')
            .selectAll('line').data(links).enter()
            .append('line')
            .attr('stroke', d => `rgba(255,215,0,${Math.max(d.strength * 0.6, 0.1)})`)
            .attr('stroke-width', d => Math.max(d.strength * 2, 0.5));

        // Nodes
        node = g.append('g').attr('class', 'nodes')
            .selectAll('g').data(nodes).enter()
            .append('g').attr('class', 'node-group')
            .call(d3.drag()
                .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
                .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
            );

        node.append('circle')
            .attr('r', d => d.is_signal ? 16 : 8)
            .attr('fill', d => d.color || '#888')
            .attr('stroke', d => d.is_signal ? '#ffd700' : 'transparent')
            .attr('stroke-width', d => d.is_signal ? 3 : 0);

        node.append('text').attr('class', 'node-label')
            .text(d => {
                const t = d.full_title || d.title || '';
                return t.split(' ').slice(0, 4).join(' ') + (t.split(' ').length > 4 ? '...' : '');
            })
            .attr('dy', d => d.is_signal ? 24 : 18)
            .attr('text-anchor', 'middle')
            .style('opacity', showLabels ? 1 : 0);

        // Mouse events
        node.on('mouseover', (e, d) => {
            tooltip.querySelector('.tt-title').textContent = d.full_title || d.title || '';
            tooltip.querySelector('.tt-meta').textContent = `${d.source || ''} | ${d.sentiment || ''}`;
            tooltip.querySelector('.tt-keywords').textContent = '🔗 ' + ((d.keywords || []).slice(0, 5)).join(', ');
            tooltip.style.opacity = 1;
        })
        .on('mousemove', (e) => {
            tooltip.style.left = (e.clientX + 15) + 'px';
            tooltip.style.top = (e.clientY - 10) + 'px';
        })
        .on('mouseout', () => { tooltip.style.opacity = 0; })
        .on('click', (e, d) => { if (d.url) window.open(d.url, '_blank'); });

        // Simulation
        sim = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(d => 150 - d.strength * 50))
            .force('charge', d3.forceManyBody().strength(-350))
            .force('center', centerForce)
            .force('collision', d3.forceCollide().radius(d => (d.is_signal ? 18 : 10) + 25));

        sim.on('tick', () => {
            link.attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
            node.attr('transform', d => {
                d.x = Math.max(30, Math.min(width - 30, d.x));
                d.y = Math.max(30, Math.min(height - 30, d.y));
                return `translate(${d.x},${d.y})`;
            });
        });
    }

    // Fetch data from API (same as Dash app)
    function fetchData() {
        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject(new Error('API error')))
            .then(data => renderGraph(data))
            .catch(err => {
                // Fallback: try to get data directly
                console.log('API not available, using embedded data');
            });
    }

    // Check if API is available, otherwise use window.graphData
    if (window.graphData) {
        renderGraph(window.graphData);
    } else {
        // Try API endpoint
        fetchData();
        // Fallback: wait for window.graphData to be set by parent
        setTimeout(() => {
            if (window.graphData) renderGraph(window.graphData);
        }, 2000);
    }

    // Resize handler
    window.addEventListener('resize', () => {
        width = window.innerWidth;
        height = window.innerHeight;
        svg.attr('width', width).attr('height', height);
        if (sim) {
            sim.force('center', d3.forceCenter(width / 2, height / 2));
            sim.alpha(0.1).restart();
        }
    });
    </script>
</body>
</html>
"""

# ==============================================================================
# TAB 1: NEWS GRAPH (D3.js via iframe)
# ==============================================================================

def tab_news_graph():
    st.markdown("### 📊 News Relationship Graph")

    # Provide graph data to the iframe via query params or postMessage
    # For simplicity, we'll embed the data in the HTML directly via a special endpoint
    graph_data = get_graph_data()

    # Create a data URL for the iframe
    data_json = json.dumps(graph_data, ensure_ascii=False)

    # We'll use st.components to embed the D3 graph
    # Since we can't easily pass Python data to an iframe srcdoc without a server,
    # let's use a different approach: embed the D3 graph directly in an HTML component

    d3_html = get_d3_graph_html()

    # Inject the graph data as a global variable
    d3_html = d3_html.replace(
        "if (window.graphData) {",
        f"window.graphData = {data_json};\n        if (window.graphData) {{"
    )

    st.components.v1.html(d3_html, height=700, scrolling=False)

# ==============================================================================
# TAB 2: SIGNAL FEED (Pure Streamlit)
# ==============================================================================

def tab_signal_feed():
    st.markdown("### ⚡ Active Trading Signals")

    signals = get_active_signals(limit=20)

    if not signals:
        st.info("No active signals yet. Run `ai_analyzer.py` to generate signals.")
        return

    # Stats row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        long_count = sum(1 for s in signals if s["direction"] == "long")
        st.metric("LONG Signals", long_count)
    with col2:
        short_count = sum(1 for s in signals if s["direction"] == "short")
        st.metric("SHORT Signals", short_count)
    with col3:
        avg_conf = int(sum(s["confidence"] for s in signals) / len(signals) * 100) if signals else 0
        st.metric("Avg Confidence", f"{avg_conf}%")
    with col4:
        unique_assets = len(set(s["asset_class"] for s in signals))
        st.metric("Asset Classes", unique_assets)

    st.divider()

    # Signal cards
    for sig in signals:
        direction_color = "signal-long" if sig["direction"] == "long" else \
                         "signal-short" if sig["direction"] == "short" else "signal-neutral"
        dir_label = sig["direction"].upper()
        conf_pct = int(sig["confidence"] * 100)
        asset = sig["asset_class"].upper()
        asset_color = ASSET_COLORS.get(sig["asset_class"], COLORS["neutral"])

        col1, col2 = st.columns([1, 3])
        with col1:
            st.markdown(f"""
            <div class="signal-card {direction_color}" style="text-align:center; padding: 20px;">
                <div style="font-size: 20px; font-weight: 700; color: {'#00ff88' if sig['direction']=='long' else '#ff4757' if sig['direction']=='short' else '#888'};">
                    {dir_label}
                </div>
                <div style="font-size: 14px; font-weight: 600; color: {asset_color}; margin-top: 6px;">
                    {asset}
                </div>
                <div style="font-size: 24px; font-weight: 700; color: #ffd700; margin-top: 8px;">
                    {conf_pct}%
                </div>
                <div style="font-size: 10px; color: #888; margin-top: 4px;">confidence</div>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
            <div class="signal-card {direction_color}" style="padding: 16px;">
                <div style="font-size: 13px; font-weight: 600; color: #e0e0e0; margin-bottom: 8px; line-height: 1.4;">
                    {sig['headline']}
                </div>
                <div style="font-size: 11px; color: #888; margin-bottom: 6px;">
                    📰 {sig.get('source_name', 'Unknown')} • ⏱ {sig.get('time_horizon', 'N/A')} • 🕐 {sig.get('generated_at', '')}
                </div>
                {f"<div style='font-size: 11px; color: #00d4ff; margin-top: 6px;'>📝 {sig.get('rationale', '')[:150]}...</div>" if sig.get('rationale') else ""}
                {f"<div style='margin-top: 8px; font-size: 10px; color: #888;'>🎯 Entry: {sig.get('entry_price', 'N/A')} | 🛑 SL: {sig.get('stop_loss', 'N/A')} | 🚪 Exit: {sig.get('exit_price', 'N/A')}</div>" if sig.get('entry_price') else ""}
            </div>
            """, unsafe_allow_html=True)

    # Footer
    st.divider()
    st.caption(f"Showing {len(signals)} active signals • Auto-refreshes every 30 seconds")

# ==============================================================================
# TAB 3: LATEST ARTICLES
# ==============================================================================

def tab_latest_articles():
    st.markdown("### 📰 Latest Articles")

    articles = get_latest_articles(limit=50)

    if not articles:
        st.info("No articles yet. Run `collector.py` to fetch news.")
        return

    # Stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Articles", len(articles))
    with col2:
        signal_count = sum(1 for a in articles if a.get("is_trading_signal"))
        st.metric("With Signals", signal_count)
    with col3:
        analyzed = sum(1 for a in articles if a.get("is_analyzed"))
        st.metric("Analyzed", analyzed)

    st.divider()

    # Sentiment filter
    sentiment_filter = st.selectbox("Filter by sentiment", ["All", "positive", "negative", "neutral"])

    filtered = articles
    if sentiment_filter != "All":
        filtered = [a for a in articles if a.get("sentiment_label") == sentiment_filter]

    # Article list
    for art in filtered:
        sent_color = "#00ff88" if art.get("sentiment_label") == "positive" else \
                    "#ff4757" if art.get("sentiment_label") == "negative" else "#888"
        sent_icon = "🟢" if art.get("sentiment_label") == "positive" else \
                   "🔴" if art.get("sentiment_label") == "negative" else "⚪"

        st.markdown(f"""
        <div class="article-item">
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 6px;">
                <span style="font-size: 13px; font-weight: 600; color: #e0e0e0; flex: 1;">{art['title']}</span>
                <span style="font-size: 11px; color: {sent_color}; margin-left: 10px; white-space: nowrap;">
                    {sent_icon} {art.get('sentiment_label', 'neutral')}
                </span>
            </div>
            <div style="font-size: 11px; color: #888;">
                📰 {art.get('source_name', 'Unknown')} • 🏷 {art.get('category', 'general')} •
                🕐 {art.get('published_at', art.get('fetched_at', ''))[:16] if art.get('published_at') or art.get('fetched_at') else 'N/A'}
                {' • ⚡ SIGNAL' if art.get('is_trading_signal') else ''}
            </div>
            {f"<div style='font-size: 11px; color: #00d4ff; margin-top: 4px;'>💬 {art.get('summary', '')[:150]}...</div>" if art.get('summary') else ""}
        </div>
        """, unsafe_allow_html=True)

        st.divider()

    st.caption(f"Showing {len(filtered)} of {len(articles)} articles")

# ==============================================================================
# TAB 4: SENTIMENT ANALYSIS (Plotly)
# ==============================================================================

def tab_sentiment_analysis():
    st.markdown("### 🎭 Sentiment Analysis")

    articles = get_latest_articles(limit=100)

    if not articles:
        st.info("No articles to analyze.")
        return

    col1, col2 = st.columns(2)

    # Sentiment distribution pie
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    for a in articles:
        label = a.get("sentiment_label", "neutral")
        if label in sentiment_counts:
            sentiment_counts[label] += 1

    with col1:
        st.markdown("#### Sentiment Distribution")
        fig_pie = go.Figure(data=[go.Pie(
            labels=["🟢 Positive", "🔴 Negative", "⚪ Neutral"],
            values=[sentiment_counts["positive"], sentiment_counts["negative"], sentiment_counts["neutral"]],
            marker=dict(colors=["#00ff88", "#ff4757", "#888"]),
            textinfo="label+percent",
            textfont=dict(color="#e0e0e0"),
            hole=0.4
        )])
        fig_pie.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=30, b=30, l=30, r=30),
            height=300,
            showlegend=True,
            legend=dict(font=dict(color="#e0e0e0"))
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    # Sentiment by source
    with col2:
        st.markdown("#### Articles by Source")
        sources = {}
        for a in articles:
            src = a.get("source_name", "Unknown")
            if src not in sources:
                sources[src] = {"positive": 0, "negative": 0, "neutral": 0}
            label = a.get("sentiment_label", "neutral")
            if label in sources[src]:
                sources[src][label] += 1

        source_names = list(sources.keys())[:10]
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(name="Positive", x=source_names,
                                  y=[sources[s]["positive"] for s in source_names],
                                  marker_color="#00ff88"))
        fig_bar.add_trace(go.Bar(name="Negative", x=source_names,
                                  y=[sources[s]["negative"] for s in source_names],
                                  marker_color="#ff4757"))
        fig_bar.add_trace(go.Bar(name="Neutral", x=source_names,
                                  y=[sources[s]["neutral"] for s in source_names],
                                  marker_color="#888"))
        fig_bar.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            barmode="stack",
            margin=dict(t=30, b=60, l=40, r=20),
            height=300,
            xaxis=dict(tickangle=-45, color="#888"),
            yaxis=dict(color="#888"),
            legend=dict(font=dict(color="#e0e0e0")),
            showlegend=True
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # Sentiment score histogram
    st.markdown("#### Sentiment Score Distribution")
    scores = [a.get("sentiment_score", 0) for a in articles if a.get("sentiment_score") is not None]

    if scores:
        fig_hist = go.Figure(data=[go.Histogram(
            x=scores,
            nbinsx=20,
            marker_color="#ffd700",
            opacity=0.8
        )])
        fig_hist.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=30, b=40, l=40, r=20),
            height=250,
            xaxis=dict(title="Sentiment Score", color="#888"),
            yaxis=dict(title="Article Count", color="#888"),
            showlegend=False
        )
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("No sentiment scores available yet.")

    # Time-based sentiment
    st.markdown("#### Sentiment Timeline")
    articles_with_time = [a for a in articles if a.get("published_at")]
    if articles_with_time:
        articles_with_time.sort(key=lambda x: x["published_at"])
        times = [a["published_at"][:16] for a in articles_with_time[-20:]]
        scores_t = [a.get("sentiment_score", 0) for a in articles_with_time[-20:]]

        fig_line = go.Figure(data=[go.Scatter(
            x=times, y=scores_t,
            mode="lines+markers",
            line=dict(color="#ffd700", width=2),
            marker=dict(size=8, color="#ffd700"),
            fill="tozeroy",
            fillcolor="rgba(255,215,0,0.1)"
        )])
        fig_line.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=30, b=60, l=40, r=20),
            height=250,
            xaxis=dict(tickangle=-45, color="#888"),
            yaxis=dict(range=[-1.1, 1.1], color="#888", title="Score"),
            showlegend=False
        )
        st.plotly_chart(fig_line, use_container_width=True)

# ==============================================================================
# TAB 5: SIGNAL ANALYTICS (Plotly)
# ==============================================================================

def tab_signal_analytics():
    st.markdown("### 📈 Signal Analytics")

    signals = get_active_signals(limit=50)

    if not signals:
        st.info("No signals yet.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Signals", len(signals))
    with col2:
        long_ct = sum(1 for s in signals if s["direction"] == "long")
        st.metric("LONG", long_ct)
    with col3:
        short_ct = sum(1 for s in signals if s["direction"] == "short")
        st.metric("SHORT", short_ct)
    with col4:
        avg_conf = int(sum(s["confidence"] for s in signals) / len(signals) * 100)
        st.metric("Avg Confidence", f"{avg_conf}%")

    st.divider()

    col1, col2 = st.columns(2)

    # Signal direction distribution
    with col1:
        st.markdown("#### Direction Distribution")
        directions = {"long": 0, "short": 0, "neutral": 0}
        for s in signals:
            d = s.get("direction", "neutral")
            if d in directions:
                directions[d] += 1

        fig_dir = go.Figure(data=[go.Pie(
            labels=["🟢 LONG", "🔴 SHORT", "⚪ NEUTRAL"],
            values=[directions["long"], directions["short"], directions["neutral"]],
            marker=dict(colors=["#00ff88", "#ff4757", "#888"]),
            hole=0.4
        )])
        fig_dir.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=20, b=20, l=20, r=20),
            height=280,
            showlegend=True
        )
        st.plotly_chart(fig_dir, use_container_width=True)

    # Asset class distribution
    with col2:
        st.markdown("#### Asset Class Distribution")
        assets = {}
        for s in signals:
            a = s.get("asset_class", "multi")
            assets[a] = assets.get(a, 0) + 1

        asset_labels = list(assets.keys())
        asset_values = list(assets.values())
        asset_colors = [ASSET_COLORS.get(a, "#888") for a in asset_labels]

        fig_asset = go.Figure(data=[go.Bar(
            x=asset_labels, y=asset_values,
            marker_color=asset_colors,
            text=asset_values,
            textposition="outside"
        )])
        fig_asset.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=20, b=40, l=40, r=20),
            height=280,
            xaxis=dict(color="#888", tickangle=-30),
            yaxis=dict(color="#888"),
            showlegend=False
        )
        st.plotly_chart(fig_asset, use_container_width=True)

    # Confidence distribution
    st.markdown("#### Confidence Levels")
    conf_values = [int(s["confidence"] * 100) for s in signals]

    fig_conf = go.Figure()
    fig_conf.add_trace(go.Histogram(
        x=conf_values, nbinsx=10,
        marker_color="#00d4ff",
        opacity=0.8
    ))
    fig_conf.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0e0"),
        margin=dict(t=20, b=40, l=40, r=20),
        height=250,
        xaxis=dict(title="Confidence %", color="#888"),
        yaxis=dict(title="Count", color="#888"),
        showlegend=False
    )
    st.plotly_chart(fig_conf, use_container_width=True)

    # Signal type breakdown
    st.markdown("#### Signal Types")
    types = {}
    for s in signals:
        t = s.get("signal_type", "alpha")
        types[t] = types.get(t, 0) + 1

    if types:
        fig_type = go.Figure(data=[go.Pie(
            labels=list(types.keys()),
            values=list(types.values()),
            hole=0.4
        )])
        fig_type.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=20, b=20, l=20, r=20),
            height=250,
            showlegend=True
        )
        st.plotly_chart(fig_type, use_container_width=True)

# ==============================================================================
# TAB 6: SOURCE STATUS
# ==============================================================================

def tab_source_status():
    st.markdown("### 🌐 API Source Status")

    sources = get_sources()

    if not sources:
        st.info("No sources configured.")
        return

    col1, col2, col3 = st.columns(3)
    working = sum(1 for s in sources if s.get("is_working") == 1)
    down = sum(1 for s in sources if s.get("is_working") == 0)
    untested = sum(1 for s in sources if s.get("is_working") is None)

    with col1:
        st.metric("Total Sources", len(sources))
    with col2:
        st.metric("Working", working, delta_color="normal")
    with col3:
        st.metric("Down / Untested", down + untested, delta_color="inverse")

    st.divider()

    # Category filter
    categories = ["All"] + sorted(set(s.get("category", "") for s in sources))
    cat_filter = st.selectbox("Filter by category", categories)

    filtered = sources
    if cat_filter != "All":
        filtered = [s for s in sources if s.get("category") == cat_filter]

    # Source table
    for s in filtered:
        status = s.get("is_working")
        status_text = "✅ Working" if status == 1 else "❌ Down" if status == 0 else "⏳ Untested"
        status_class = "source-working" if status == 1 else "source-down" if status == 0 else "source-untested"

        with st.expander(f"{s.get('display_name', s.get('name', 'Unknown'))} — {s.get('category', 'N/A').upper()}", expanded=False):
            col_a, col_b = st.columns([1, 1])
            with col_a:
                st.markdown(f"**API Type:** {s.get('api_type', 'N/A')}")
                st.markdown(f"**Status:** <span class='{status_class}'>{status_text}</span>", unsafe_allow_html=True)
                if s.get("last_tested_at"):
                    st.markdown(f"**Last Tested:** {s.get('last_tested_at')[:19]}")
                if s.get("last_response_time_ms"):
                    st.markdown(f"**Response Time:** {s.get('last_response_time_ms')}ms")

            with col_b:
                if s.get("rate_limit_rpm"):
                    st.markdown(f"**Rate Limit:** {s.get('rate_limit_rpm')} req/min")
                if s.get("monthly_cost_usd"):
                    st.markdown(f"**Cost:** ${s.get('monthly_cost_usd')}/mo")
                st.markdown(f"**Active:** {'Yes' if s.get('is_active') else 'No'}")
                if s.get("description"):
                    st.markdown(f"**Description:** {s.get('description')[:100]}")

# ==============================================================================
# TAB 7: MARKET PULSE
# ==============================================================================

def tab_market_pulse():
    st.markdown("### 📈 Market Pulse")

    prices = get_market_prices(limit=100)

    # Stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Price Records", len(prices))
    with col2:
        symbols = len(set(p.get("symbol") for p in prices))
        st.metric("Symbols Tracked", symbols)
    with col3:
        if prices:
            latest = prices[0].get("fetched_at", "N/A")[:16] if prices else "N/A"
            st.metric("Last Update", latest)

    st.divider()

    if not prices:
        st.info("No market price data yet. Market prices are populated by the collector.")
        return

    # Symbol filter
    symbols = sorted(set(p.get("symbol") for p in prices))
    selected = st.selectbox("Select Symbol", symbols)

    symbol_prices = [p for p in prices if p.get("symbol") == selected]
    symbol_prices.sort(key=lambda x: x.get("fetched_at", ""))

    if len(symbol_prices) > 1:
        fig_price = go.Figure()
        fig_price.add_trace(go.Scatter(
            x=[p.get("fetched_at", "")[:16] for p in symbol_prices],
            y=[p.get("price", 0) for p in symbol_prices],
            mode="lines+markers",
            line=dict(color="#ffd700", width=2),
            marker=dict(size=6, color="#ffd700"),
            fill="tozeroy",
            fillcolor="rgba(255,215,0,0.1)"
        ))
        fig_price.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e0e0e0"),
            margin=dict(t=20, b=50, l=50, r=20),
            height=350,
            xaxis=dict(tickangle=-45, color="#888"),
            yaxis=dict(color="#888", title="Price"),
            showlegend=False
        )
        st.plotly_chart(fig_price, use_container_width=True)

        # Change %
        if symbol_prices[-1].get("change_pct") is not None:
            change = symbol_prices[-1]["change_pct"]
            change_color = "#00ff88" if change >= 0 else "#ff4757"
            st.markdown(f"**Change:** <span style='color:{change_color};font-size:18px;font-weight:700;'>{'+' if change >= 0 else ''}{change:.2f}%</span>", unsafe_allow_html=True)

    # All symbols overview
    st.markdown("#### All Symbols Overview")
    unique_prices = {}
    for p in prices:
        sym = p.get("symbol")
        if sym not in unique_prices:
            unique_prices[sym] = p

    cols = st.columns(min(len(unique_prices), 4))
    for i, (sym, p) in enumerate(unique_prices.items()):
        with cols[i % 4]:
            change = p.get("change_pct", 0)
            change_color = "#00ff88" if change >= 0 else "#ff4757"
            st.metric(
                sym,
                f"${p.get('price', 0):.4f}" if p.get("price") else "N/A",
                f"{'+' if change >= 0 else ''}{change:.2f}%" if change is not None else None,
                delta_color="normal" if change >= 0 else "inverse"
            )

# ==============================================================================
# TAB 8: KEYWORD EXPLORER
# ==============================================================================

def tab_keyword_explorer():
    st.markdown("### 🔑 Keyword Explorer")

    articles = get_latest_articles(limit=50)

    if not articles:
        st.info("No articles yet.")
        return

    # Extract keywords from all articles
    all_keywords = {}
    for art in articles:
        text = f"{art['title']} {art.get('summary', '')}".lower()
        words = re.findall(r'\b\w{4,}\b', text)
        stop_words = {
            'that', 'this', 'with', 'from', 'have', 'been', 'were', 'they',
            'what', 'when', 'where', 'which', 'about', 'would', 'could',
            'from', 'their', 'there', 'being', 'after', 'more', 'also',
            'just', 'very', 'will', 'would', 'could', 'should', 'about',
            'over', 'such', 'into', 'only', 'other', 'then', 'than', 'both',
            'your', 'more', 'some', 'these', 'those', 'each', 'even', 'just',
            'like', 'says', 'said', 'year', 'years', 'new', 'first', 'last',
            'many', 'much', 'well', 'back', 'still', 'because', 'before',
            'going', 'while', 'though', 'most', 'make', 'made', 'take',
            'know', 'come', 'came', 'look', 'want', 'give', 'great', 'good'
        }
        for w in words:
            if w not in stop_words and len(w) > 3:
                all_keywords[w] = all_keywords.get(w, 0) + 1

    # Sort by frequency
    sorted_kw = sorted(all_keywords.items(), key=lambda x: x[1], reverse=True)[:50]

    col1, col2 = st.columns([1, 2])

    with col1:
        st.markdown("#### Top Keywords")
        for kw, count in sorted_kw[:25]:
            bar_width = int(count / sorted_kw[0][1] * 100)
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="width:80px;font-size:11px;color:#e0e0e0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{kw}</span>
                <div style="flex:1;height:16px;background:rgba(255,215,0,0.1);border-radius:3px;overflow:hidden;">
                    <div style="width:{bar_width}%;height:100%;background:#ffd700;opacity:{0.4 + bar_width/200:.1};"></div>
                </div>
                <span style="width:25px;text-align:right;font-size:10px;color:#888;">{count}</span>
            </div>
            """, unsafe_allow_html=True)

    with col2:
        st.markdown("#### Keyword Network")

        # Build co-occurrence matrix
        keyword_articles = {}
        for art in articles:
            text = f"{art['title']} {art.get('summary', '')}".lower()
            words = re.findall(r'\b\w{4,}\b', text)
            top_words = [w for w in words if w in dict(sorted_kw[:20]) and w not in stop_words]
            for w in set(top_words):
                if w not in keyword_articles:
                    keyword_articles[w] = []
                keyword_articles[w].append(art["id"])

        # Find co-occurring pairs
        cooccur = {}
        article_keywords = {}
        for art in articles:
            text = f"{art['title']} {art.get('summary', '')}".lower()
            words = [w for w in re.findall(r'\b\w{4,}\b', text) if w in dict(sorted_kw[:20]) and w not in stop_words]
            article_keywords[art["id"]] = set(words)

        for art_id, kws in article_keywords.items():
            kw_list = sorted(kws)
            for i, kw1 in enumerate(kw_list):
                for kw2 in kw_list[i+1:]:
                    pair = tuple(sorted([kw1, kw2]))
                    cooccur[pair] = cooccur.get(pair, 0) + 1

        # Show strongest keyword pairs
        strong_pairs = sorted(cooccur.items(), key=lambda x: x[1], reverse=True)[:20]

        for (kw1, kw2), count in strong_pairs:
            bar_width = int(count / strong_pairs[0][1] * 100)
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span style="width:70px;font-size:11px;color:#00d4ff;overflow:hidden;text-overflow:ellipsis;">{kw1}</span>
                <span style="color:#888;font-size:10px;">↔</span>
                <span style="width:70px;font-size:11px;color:#00d4ff;overflow:hidden;text-overflow:ellipsis;">{kw2}</span>
                <div style="flex:1;height:14px;background:rgba(0,212,255,0.1);border-radius:3px;overflow:hidden;">
                    <div style="width:{bar_width}%;height:100%;background:#00d4ff;opacity:{0.4 + bar_width/200:.1};"></div>
                </div>
                <span style="width:20px;text-align:right;font-size:10px;color:#888;">{count}</span>
            </div>
            """, unsafe_allow_html=True)

    # Keyword by sentiment
    st.markdown("#### Keyword Sentiment Heatmap")

    # Get top keywords and their sentiment distribution
    top_kw = dict(sorted_kw[:15])
    kw_sentiment = {kw: {"positive": 0, "negative": 0, "neutral": 0} for kw in top_kw}

    for art in articles:
        text = f"{art['title']} {art.get('summary', '')}".lower()
        sent = art.get("sentiment_label", "neutral")
        for kw in top_kw:
            if kw in text:
                kw_sentiment[kw][sent] = kw_sentiment[kw].get(sent, 0) + 1

    # Build heatmap data
    kw_list = list(top_kw.keys())
    pos_vals = [kw_sentiment[kw]["positive"] for kw in kw_list]
    neg_vals = [kw_sentiment[kw]["negative"] for kw in kw_list]
    neu_vals = [kw_sentiment[kw]["neutral"] for kw in kw_list]

    fig_heat = go.Figure()
    fig_heat.add_trace(go.Bar(name="Positive", x=kw_list, y=pos_vals, marker_color="#00ff88"))
    fig_heat.add_trace(go.Bar(name="Negative", x=kw_list, y=neg_vals, marker_color="#ff4757"))
    fig_heat.add_trace(go.Bar(name="Neutral", x=kw_list, y=neu_vals, marker_color="#888"))
    fig_heat.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0e0", size=10),
        barmode="group",
        margin=dict(t=20, b=80, l=40, r=20),
        height=300,
        xaxis=dict(tickangle=-45, color="#888"),
        yaxis=dict(color="#888"),
        legend=dict(font=dict(color="#e0e0e0"))
    )
    st.plotly_chart(fig_heat, use_container_width=True)

# ==============================================================================
# MAIN APP
# ==============================================================================

def main():
    # Header
    st.markdown("""
    <div style="display:flex;justify-content:space-between;align-items:center;padding:16px 0;border-bottom:1px solid rgba(255,215,0,0.15);margin-bottom:20px;">
        <div style="display:flex;align-items:center;gap:12px;">
            <span style="font-size:28px;">🏆</span>
            <span style="color:#ffd700;font-size:22px;font-weight:700;font-family:Inter,sans-serif;">Golden News</span>
        </div>
        <div style="display:flex;align-items:center;gap:16px;">
            <span style="color:#00ff88;font-size:12px;font-weight:600;">● LIVE</span>
            <span style="color:#888;font-size:12px;">Updated: {}</span>
        </div>
    </div>
    """.format(datetime.now().strftime("%H:%M:%S")), unsafe_allow_html=True)

    # Create 8 tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📊 News Graph",
        "⚡ Signal Feed",
        "📰 Latest Articles",
        "🎭 Sentiment",
        "📈 Signal Analytics",
        "🌐 Source Status",
        "📈 Market Pulse",
        "🔑 Keywords"
    ])

    with tab1:
        tab_news_graph()
    with tab2:
        tab_signal_feed()
    with tab3:
        tab_latest_articles()
    with tab4:
        tab_sentiment_analysis()
    with tab5:
        tab_signal_analytics()
    with tab6:
        tab_source_status()
    with tab7:
        tab_market_pulse()
    with tab8:
        tab_keyword_explorer()

if __name__ == "__main__":
    main()

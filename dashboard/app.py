#!/usr/bin/env python3
"""
Golden News Dashboard - Plotly Dash + Multiple Visualization Libraries
Real-time news graph visualization with trading signals
Layout: Original sidebar + tabbed viz panels
"""
import sqlite3
import json
import re
from pathlib import Path
import dash
from dash import dcc, html, callback, Output, Input, State
import plotly.graph_objects as go
import plotly.express as px
from flask import Flask, jsonify

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

# Use Flask server for API endpoints
server = Flask(__name__)
app = dash.Dash(__name__, server=server, title="Golden News Dashboard")

# Google Fonts
app.index_string = '''
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%css%}
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>
'''

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
        SELECT ts.*, a.title as article_title,
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
    """Build nodes and edges for force-directed graph"""
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
        keyword_map[art["id"]] = keywords

        text = f"{art['title']} {art.get('summary', '')}".lower()
        words = re.findall(r'\b\w{4,}\b', text)
        stop_words = {'that', 'this', 'with', 'from', 'have', 'been', 'were', 'they',
                      'what', 'when', 'where', 'which', 'about', 'would', 'could',
                      'their', 'there', 'would', 'still', 'will', 'more', 'most',
                      'some', 'into', 'only', 'over', 'such', 'after', 'before'}
        keyword_set = set(w for w in words if w not in stop_words)
        keyword_map[art["id"]].extend(list(keyword_set)[:5])

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
            "size": 10 if art.get("is_trading_signal") else 6,
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

# =============================================================================
# API ENDPOINTS
# =============================================================================

@server.route('/health')
def health():
    return jsonify({"status": "ok"})

@server.route('/api/graph-data')
def api_graph_data():
    data = get_graph_data()
    return jsonify(data, ensure_ascii=False)

@server.route('/api/signals')
def api_signals():
    signals = get_active_signals(limit=20)
    return jsonify(signals)

@server.route('/api/articles')
def api_articles():
    articles = get_latest_articles(limit=50)
    return jsonify(articles)

# =============================================================================
# CSS styles (injected once)
# =============================================================================

DASHBOARD_CSS = f"""
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: {COLORS['background']}; font-family: 'Inter', sans-serif; }}
    .tab-header {{
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px; background: {COLORS['card_bg']};
        borderBottom: 1px solid {COLORS['primary']}22;
    }}
    .tab-bar {{
        display: flex; gap: 4px; padding: 0 16px;
        background: {COLORS['background']};
        border-bottom: 1px solid {COLORS['primary']}22;
    }}
    .tab-btn {{
        padding: 10px 16px; background: transparent; border: none;
        color: {COLORS['neutral']}; font-size: 13px; font-weight: 500;
        cursor: pointer; border-bottom: 2px solid transparent;
        transition: all 0.2s; font-family: 'Inter', sans-serif;
    }}
    .tab-btn:hover {{ color: {COLORS['text']}; }}
    .tab-btn.active {{
        color: {COLORS['primary']}; border-bottom: 2px solid {COLORS['primary']};
        font-weight: 600;
    }}
    .viz-panel {{
        display: none; height: calc(100vh - 120px);
        background: {COLORS['background']};
    }}
    .viz-panel.active {{ display: block; }}
    .sidebar {{
        width: 380px; background: {COLORS['card_bg']};
        border-left: 1px solid {COLORS['primary']}11;
        height: calc(100vh - 60px); overflow-y: auto;
    }}
    .main-area {{
        display: flex; height: calc(100vh - 60px); overflow: hidden;
    }}
    .viz-container {{ height: calc(100vh - 120px); position: relative; overflow: hidden; }}
    .viz-container svg {{ display: block; width: 100%; height: 100%; }}
    .signal-card {{
        background: {COLORS['background']}; border-radius: 6px; padding: 10px;
        margin-bottom: 8px; border-left: 3px solid;
    }}
    .signal-card.long {{ border-left-color: {COLORS['positive']}; }}
    .signal-card.short {{ border-left-color: {COLORS['negative']}; }}
    .signal-card.neutral {{ border-left-color: {COLORS['neutral']}; }}
    .article-item {{
        padding: 8px 0; border-bottom: 1px solid {COLORS['primary']}11;
    }}
    .article-item a {{ text-decoration: none; }}
    .section-title {{
        color: {COLORS['primary']}; font-size: 14px; font-weight: 600;
        padding: 12px 16px 8px;
    }}
    .empty-state {{
        color: {COLORS['neutral']}; font-size: 12px; padding: 20px;
        text-align: center;
    }}
    /* Override Dash's default tab styles */
    .Tabs {{ background: {COLORS['background']}; }}
</style>
"""

# =============================================================================
# D3.js GRAPH BUILDER (embedded as clientside callback)
# =============================================================================

D3_BUILD_GRAPH_JS = r"""
function buildGraph(container) {
    var width  = container.clientWidth  || window.innerWidth  - 380;
    var height = container.clientHeight || window.innerHeight - 60;

    // SVG
    var svgNS = 'http://www.w3.org/2000/svg';
    var svgEl = document.createElementNS(svgNS, 'svg');
    svgEl.setAttribute('width', width);
    svgEl.setAttribute('height', height);
    svgEl.style.background = '#0a0e17';
    container.appendChild(svgEl);
    var svg = d3.select(svgEl);
    var g   = svg.append('g');

    // Tooltip
    var tooltip = document.createElement('div');
    tooltip.id = 'graph-tooltip';
    tooltip.innerHTML = '<div class="tt-title"></div><div class="tt-meta"></div><div class="tt-keywords"></div>';
    tooltip.style.cssText = 'position:absolute;background:#1a1f2e;border:1px solid #ffd700;border-radius:8px;padding:12px;font-size:12px;max-width:340px;pointer-events:none;opacity:0;z-index:100;box-shadow:0 4px 20px rgba(0,0,0,0.5);font-family:Inter,sans-serif;';
    container.appendChild(tooltip);

    // Zoom
    var zoom = d3.zoom()
        .scaleExtent([0.2, 4])
        .on('zoom', function(e) { g.attr('transform', e.transform); });
    svg.call(zoom);

    // Controls panel
    var ctrl = document.createElement('div');
    ctrl.style.cssText = 'position:absolute;top:16px;left:16px;background:rgba(26,31,46,0.95);border-radius:8px;padding:12px 16px;font-size:11px;z-index:10;border:1px solid rgba(255,215,0,0.2);font-family:Inter,sans-serif;';
    ctrl.innerHTML = '<div style="margin-bottom:8px"><span style="color:#ffd700;font-weight:600">Nodes:</span><input type="range" id="gn-node-slider" min="5" max="40" value="15" style="width:90px;accent-color:#ffd700;margin:0 8px"><span id="gn-node-count" style="color:#e0e0e0;min-width:20px;display:inline-block">15</span></div><div><button id="gn-reset-btn" style="background:rgba(255,215,0,0.15);border:1px solid rgba(255,215,0,0.4);color:#ffd700;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:10px">Reset</button><button id="gn-labels-btn" style="background:rgba(255,215,0,0.15);border:1px solid rgba(255,215,0,0.4);color:#ffd700;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:10px;margin-left:8px">Labels</button></div>';
    container.appendChild(ctrl);

    document.getElementById('gn-reset-btn').onclick = function() {
        svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
    };
    document.getElementById('gn-labels-btn').onclick = function() {
        window.gnShowLabels = !window.gnShowLabels;
        svg.selectAll('.node-label').style('opacity', window.gnShowLabels ? 1 : 0);
    };
    var slider = document.getElementById('gn-node-slider');
    slider.addEventListener('input', function() {
        document.getElementById('gn-node-count').textContent = this.value;
        window.gnNodeLimit = +this.value;
        svg.selectAll('.node-group').style('display',
            function(d, i) { return i < window.gnNodeLimit ? 'block' : 'none'; });
    });

    // Stats text
    var statsText = svg.append('text')
        .attr('x', width - 20).attr('y', height - 20)
        .attr('text-anchor', 'end').attr('fill', '#888').attr('font-size', '10px')
        .attr('font-family', 'Inter, sans-serif').text('Loading...');

    // Legend
    var legend = svg.append('g').attr('transform', 'translate(16,' + (height - 105) + ')');
    legend.append('rect').attr('width', 100).attr('height', 92)
        .attr('fill', 'rgba(26,31,46,0.95)').attr('rx', 6)
        .attr('stroke', 'rgba(255,215,0,0.15)');
    legend.append('text').attr('x', 10).attr('y', 18)
        .attr('fill', '#ffd700').attr('font-size', '10px').attr('font-weight', '600')
        .attr('font-family', 'Inter, sans-serif').text('Sentiment');
    [
        { color: '#00ff88', label: 'Positive' },
        { color: '#ff4757', label: 'Negative' },
        { color: '#888',    label: 'Neutral'  },
        { color: '#ffd700', label: 'Signal',  ring: true }
    ].forEach(function(item, i) {
        var y = 34 + i * 15;
        if (item.ring) {
            legend.append('circle').attr('cx', 15).attr('cy', y - 4).attr('r', 5)
                .attr('fill', 'transparent').attr('stroke', item.color).attr('stroke-width', 2);
        } else {
            legend.append('circle').attr('cx', 15).attr('cy', y - 4).attr('r', 4).attr('fill', item.color);
        }
        legend.append('text').attr('x', 28).attr('y', y)
            .attr('fill', '#e0e0e0').attr('font-size', '9px')
            .attr('font-family', 'Inter, sans-serif').text(item.label);
    });

    window.gnShowLabels = true;
    window.gnNodeLimit  = 15;

    function renderGraph() {
        fetch('/api/graph-data')
            .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error('API ' + r.status)); })
            .then(function(data) {
                if (!data.nodes || data.nodes.length === 0) {
                    svg.append('text').attr('x', width/2).attr('y', height/2)
                        .attr('fill', '#888').attr('text-anchor', 'middle')
                        .attr('font-family', 'Inter, sans-serif')
                        .text('No articles yet. Run collector.py to fetch news.');
                    return;
                }

                statsText.text(data.nodes.length + ' articles | ' + (data.edges ? data.edges.length : 0) + ' connections');

                var nodes = data.nodes.map(function(n) {
                    return {
                        x: width/2  + (Math.random() - 0.5) * Math.min(width * 0.4, 400),
                        y: height/2 + (Math.random() - 0.5) * Math.min(height * 0.4, 300),
                        color: n.color, full_title: n.full_title, title: n.title,
                        url: n.url, source: n.source, sentiment: n.sentiment,
                        is_signal: n.is_signal, keywords: n.keywords, id: n.id
                    };
                });
                var nodeMap = new Map(nodes.map(function(n) { return [n.id, n]; }));
                window.gnNodes   = nodes;
                window.gnNodeMap = nodeMap;

                var links = (data.edges || []).map(function(e) {
                    return {
                        source: nodeMap.get(e.source),
                        target: nodeMap.get(e.target),
                        strength: e.strength,
                        shared:   e.shared_keywords || []
                    };
                }).filter(function(e) { return e.source && e.target; });
                window.gnLinks = links;

                var sim = d3.forceSimulation(nodes)
                    .force('link',      d3.forceLink(links).id(function(d) { return d.id; }).distance(function(d) { return 150 - d.strength * 50; }))
                    .force('charge',     d3.forceManyBody().strength(-350))
                    .force('center',     d3.forceCenter(width/2, height/2))
                    .force('collision',  d3.forceCollide().radius(function(d) { return (d.is_signal ? 18 : 10) + 25; }));
                window.gnSim = sim;

                var link = g.append('g').attr('class', 'links')
                    .selectAll('line').data(links).enter()
                    .append('line')
                    .attr('stroke', function(d) { return 'rgba(255,215,0,' + Math.max(d.strength * 0.6, 0.1) + ')'; })
                    .attr('stroke-width', function(d) { return Math.max(d.strength * 2, 0.5); });

                var node = g.append('g').attr('class', 'nodes')
                    .selectAll('g').data(nodes).enter()
                    .append('g').attr('class', 'node-group')
                    .call(d3.drag()
                        .on('start', function(e, d) { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                        .on('drag',   function(e, d) { d.fx = e.x; d.fy = e.y; })
                        .on('end',    function(e, d) { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
                    );

                node.append('circle')
                    .attr('r', function(d) { return d.is_signal ? 16 : 8; })
                    .attr('fill', function(d) { return d.color || '#888'; })
                    .attr('stroke', function(d) { return d.is_signal ? '#ffd700' : 'transparent'; })
                    .attr('stroke-width', function(d) { return d.is_signal ? 3 : 0; });

                node.append('text').attr('class', 'node-label')
                    .text(function(d) {
                        var t = d.full_title || d.title || '';
                        var w = t.split(' ').slice(0, 4);
                        return w.join(' ') + (t.split(' ').length > 4 ? '...' : '');
                    })
                    .attr('dy',      function(d) { return d.is_signal ? 24 : 18; })
                    .attr('text-anchor', 'middle')
                    .attr('fill', '#e0e0e0').attr('font-size', '8px')
                    .attr('font-family', 'Inter, sans-serif')
                    .style('pointer-events', 'none');

                node.on('mouseover', function(e, d) {
                    tooltip.querySelector('.tt-title').textContent = d.full_title || d.title || '';
                    tooltip.querySelector('.tt-meta').textContent = (d.source || '') + ' | ' + (d.sentiment || '');
                    tooltip.querySelector('.tt-keywords').textContent = '\uD83D\uDD0D ' + ((d.keywords || []).slice(0, 5)).join(', ');
                    tooltip.style.opacity = 1;
                })
                .on('mousemove', function(e) {
                    var rect = container.getBoundingClientRect();
                    tooltip.style.left = (e.clientX - rect.left + 15) + 'px';
                    tooltip.style.top  = (e.clientY - rect.top  - 10) + 'px';
                })
                .on('mouseout',  function() { tooltip.style.opacity = 0; })
                .on('click', function(e, d) { if (d.url) window.open(d.url, '_blank'); });

                sim.on('tick', function() {
                    link.attr('x1', function(d) { return d.source.x; })
                        .attr('y1', function(d) { return d.source.y; })
                        .attr('x2', function(d) { return d.target.x; })
                        .attr('y2', function(d) { return d.target.y; });
                    node.attr('transform', function(d) {
                        d.x = Math.max(30, Math.min(width  - 30, d.x));
                        d.y = Math.max(30, Math.min(height - 30, d.y));
                        return 'translate(' + d.x + ',' + d.y + ')';
                    });
                });
            })
            .catch(function(err) {
                svg.append('text').attr('x', width/2).attr('y', height/2)
                    .attr('fill', '#ff4757').attr('text-anchor', 'middle')
                    .text('Error: ' + err.message);
            });
    }

    renderGraph();

    window.gnRefreshTimer = setInterval(function() {
        if (!window.gnSim) return;
        fetch('/api/graph-data')
            .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
            .then(function(data) {
                if (!data || !data.nodes || !data.nodes.length) return;
                statsText.text(data.nodes.length + ' articles | ' + (data.edges ? data.edges.length : 0) + ' connections');
                data.nodes.forEach(function(n) {
                    var ex = window.gnNodeMap.get(n.id);
                    if (ex) {
                        ex.color      = n.color;
                        ex.is_signal  = n.is_signal;
                        ex.keywords   = n.keywords;
                        ex.full_title = n.full_title;
                        ex.source     = n.source;
                        ex.sentiment  = n.sentiment;
                    }
                });
                window.gnSim.alpha(0.1).restart();
            }).catch(function() {});
    }, 30000);
}
"""

D3_INIT_CSS = """
#d3-panel { position: relative; overflow: hidden; }
#graph-tooltip .tt-title { color: #e0e0e0; font-weight: 600; font-size: 12px; }
#graph-tooltip .tt-meta { font-size: 10px; color: #888; margin-top: 6px; }
#graph-tooltip .tt-keywords { font-size: 10px; color: #00d4ff; margin-top: 4px; }
.node-group { cursor: pointer; }
.node-label { pointer-events: none; font-family: Inter, sans-serif; }
"""

# =============================================================================
# SIGNAL FEED HTML (pure HTML/CSS, no viz lib)
# =============================================================================

def build_signal_cards_html(signals):
    """Build HTML for signal cards"""
    cards = []
    for sig in signals[:20]:
        direction = sig.get('direction', 'neutral')
        conf = int(sig.get('confidence', 0) * 100)
        dir_color = COLORS['positive'] if direction == 'long' else COLORS['negative'] if direction == 'short' else COLORS['neutral']
        asset_color = ASSET_COLORS.get(sig.get('asset_class', 'multi'), COLORS['neutral'])
        card_class = 'long' if direction == 'long' else 'short' if direction == 'short' else 'neutral'
        headline = sig.get('headline', '')[:80]
        rationale = sig.get('rationale', '')[:120]
        source = sig.get('source_name', '')
        time_horizon = sig.get('time_horizon', '')
        ticker = sig.get('ticker', '')

        cards.append(f'''
        <div class="signal-card {card_class}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <span style="color:{dir_color};font-weight:700;font-size:10px">{direction.upper()}</span>
                <span style="color:{asset_color};font-weight:600;font-size:10px">{sig.get('asset_class', '').upper()}</span>
                <span style="color:{COLORS['neutral']};font-size:10px">{conf}%</span>
            </div>
            <div style="color:{COLORS['text']};font-size:11px;line-height:1.3;margin-bottom:4px">{headline}</div>
            <div style="color:{COLORS['neutral']};font-size:9px;margin-bottom:4px">{rationale}...</div>
            <div style="color:{COLORS['neutral']};font-size:9px">{source}{' | ' + ticker if ticker else ''} | {time_horizon}</div>
        </div>''')
    return ''.join(cards) if cards else f'<div class="empty-state">No signals yet.<br>Run ai_analyzer.py to generate signals.</div>'

def build_articles_html(articles):
    """Build HTML for article list"""
    items = []
    for art in articles[:20]:
        sentiment = art.get('sentiment_label', 'neutral')
        sent_color = COLORS['positive'] if sentiment == 'positive' else COLORS['negative'] if sentiment == 'negative' else COLORS['neutral']
        title = art.get('title', '')[:80]
        source = art.get('source_name', '')[:15]
        url = art.get('url', '#')
        items.append(f'''
        <div class="article-item">
            <a href="{url}" target="_blank" style="text-decoration:none">
                <div style="color:{COLORS['text']};font-size:11px;line-height:1.3;margin-bottom:4px">{title}...</div>
                <div style="display:flex;gap:6px">
                    <span style="color:{COLORS['primary']};font-size:9px">{source}</span>
                    <span style="color:{sent_color};font-size:9px">{sentiment}</span>
                </div>
            </a>
        </div>''')
    return ''.join(items) if items else f'<div class="empty-state">No articles yet.<br>Run collector.py to fetch news.</div>'

# =============================================================================
# LAYOUT
# =============================================================================

app.layout = html.Div([

    # Inject CSS
    dcc.Store(id='gn-inject-css', data={'done': False}),
    html.Div(id='css-injector'),

    # Header
    html.Div([
        html.H1("\U0001F3C6 Golden News", style={
            "color": COLORS["primary"], "fontSize": "24px", "fontWeight": "700",
            "margin": "0", "fontFamily": "Inter, sans-serif"
        }),
        html.Div([
            html.Span("\u25CF LIVE", style={"color": COLORS["positive"], "fontSize": "12px", "fontWeight": "600", "marginRight": "20px"}),
            html.Span(id="gn-last-update", style={"color": COLORS["neutral"], "fontSize": "12px"}),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={
        "display": "flex", "justifyContent": "space-between", "alignItems": "center",
        "padding": "16px 24px", "background": COLORS["card_bg"],
        "borderBottom": f"1px solid {COLORS['primary']}22", "margin": "0"
    }),

    # Main content area
    html.Div([

        # Left / Main panel area
        html.Div([

            # Tab bar
            html.Div([
                html.Button("\U0001F4CA D3 Force",    id="tab-btn-d3",    className="tab-btn active"),
                html.Button("\U0001F578 Cytoscape",   id="tab-btn-cyto",  className="tab-btn"),
                html.Button("\U0001F310 Vis.js",       id="tab-btn-vis",   className="tab-btn"),
                html.Button("\u03A3 Sigma",           id="tab-btn-sigma",  className="tab-btn"),
                html.Button("\U0001F4C8 ECharts",     id="tab-btn-ech",   className="tab-btn"),
                html.Button("\U0001F4C9 TradingView",  id="tab-btn-tv",    className="tab-btn"),
                html.Button("\U0001F4C9 Chart.js",     id="tab-btn-cj",    className="tab-btn"),
                html.Button("\u26A1 Signals",         id="tab-btn-sig",   className="tab-btn"),
            ], className="tab-bar", style={"display": "flex", "alignItems": "center", "gap": "4px", "padding": "0 16px", "background": COLORS["background"], "borderBottom": f"1px solid {COLORS['primary']}22"}),

            # Viz panels (all pre-rendered, toggled via CSS)
            # Panel 1: D3 Force Graph
            html.Div(id="panel-d3", className="viz-panel active", style={"display": "block"}, children=[
                html.Div(style={"padding": "12px 16px", "background": COLORS["card_bg"], "display": "flex", "alignItems": "center", "gap": "8px"}, children=[
                    html.Span("Nodes:", style={"color": COLORS["text"], "fontSize": "12px", "marginRight": "8px"}),
                    html.Div(style={"width": "200px", "display": "inline-block"}, children=[
                        dcc.Slider(id="d3-node-slider", min=5, max=40, value=15, step=1,
                                   tooltip={"placement": "bottom", "always_visible": False}),
                    ]),
                    html.Button("Reset View", id="d3-reset-btn", n_clicks=0,
                               style={"background": f"rgba(255,215,0,0.15)", "border": f"1px solid {COLORS['primary']}66",
                                      "color": COLORS["primary"], "padding": "6px 12px", "borderRadius": "4px",
                                      "cursor": "pointer", "fontSize": "11px", "marginLeft": "16px"}),
                    html.Button("Toggle Labels", id="d3-labels-btn", n_clicks=0,
                               style={"background": f"rgba(255,215,0,0.15)", "border": f"1px solid {COLORS['primary']}66",
                                      "color": COLORS["primary"], "padding": "6px 12px", "borderRadius": "4px",
                                      "cursor": "pointer", "fontSize": "11px", "marginLeft": "8px"}),
                ]),
                html.Div(id="d3-graph-container", className="viz-container", style={"height": "calc(100vh - 180px)"}),
            ]),

            # Panel 2: Cytoscape
            html.Div(id="panel-cyto", className="viz-panel", children=[
                html.Div("\U0001F578 Cytoscape.js Network Graph", style={
                    "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                    "padding": "12px 16px", "borderBottom": f"1px solid {COLORS['primary']}22",
                    "background": COLORS["card_bg"]
                }),
                html.Div(id="cytoscape-container", className="viz-container", style={"height": "calc(100vh - 156px)"}),
            ]),

            # Panel 3: Vis.js
            html.Div(id="panel-vis", className="viz-panel", children=[
                html.Div("\U0001F310 Vis.js Network Graph", style={
                    "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                    "padding": "12px 16px", "borderBottom": f"1px solid {COLORS['primary']}22",
                    "background": COLORS["card_bg"]
                }),
                html.Div(id="vis-container", className="viz-container", style={"height": "calc(100vh - 156px)"}),
            ]),

            # Panel 4: Sigma.js
            html.Div(id="panel-sigma", className="viz-panel", children=[
                html.Div("\u03A3 Sigma.js Graph", style={
                    "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                    "padding": "12px 16px", "borderBottom": f"1px solid {COLORS['primary']}22",
                    "background": COLORS["card_bg"]
                }),
                html.Div(id="sigma-container", className="viz-container", style={"height": "calc(100vh - 156px)"}),
            ]),

            # Panel 5: ECharts
            html.Div(id="panel-ech", className="viz-panel", children=[
                html.Div("\U0001F4C8 ECharts Timeline", style={
                    "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                    "padding": "12px 16px", "borderBottom": f"1px solid {COLORS['primary']}22",
                    "background": COLORS["card_bg"]
                }),
                html.Div(id="echarts-container", className="viz-container", style={"height": "calc(100vh - 156px)"}),
            ]),

            # Panel 6: TradingView
            html.Div(id="panel-tv", className="viz-panel", children=[
                html.Div("\U0001F4C9 TradingView Lightweight Charts", style={
                    "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                    "padding": "12px 16px", "borderBottom": f"1px solid {COLORS['primary']}22",
                    "background": COLORS["card_bg"]
                }),
                html.Div(id="tradingview-container", className="viz-container", style={"height": "calc(100vh - 156px)"}),
            ]),

            # Panel 7: Chart.js
            html.Div(id="panel-cj", className="viz-panel", children=[
                html.Div("\U0001F4C9 Chart.js Analytics", style={
                    "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                    "padding": "12px 16px", "borderBottom": f"1px solid {COLORS['primary']}22",
                    "background": COLORS["card_bg"]
                }),
                html.Div(id="chartjs-container", className="viz-container", style={"height": "calc(100vh - 156px)"}),
            ]),

            # Panel 8: Signal Feed (no viz lib, just HTML/CSS)
            html.Div(id="panel-sig", className="viz-panel", children=[
                html.Div(style={"height": "calc(100vh - 60px)", "overflow": "auto", "padding": "16px"}, children=[
                    html.Div(id="signal-feed-content", style={"display": "flex", "flexDirection": "column", "gap": "0"}),
                ]),
            ]),

        ], style={"flex": "1", "overflow": "hidden", "display": "flex", "flexDirection": "column"}),

        # Right sidebar: Signals + Articles (ORIGINAL LAYOUT PRESERVED)
        html.Div([
            html.H3("\u26A1 Signals", style={
                "color": COLORS["primary"], "fontSize": "14px", "fontWeight": "600",
                "padding": "12px 16px 8px", "margin": "0"
            }),
            html.Div(id="sidebar-signals", style={
                "maxHeight": "200px", "overflowY": "auto", "padding": "0 12px"
            }),

            html.Hr(style={"borderColor": COLORS["primary"] + "22", "margin": "12px 0"}),

            html.H3("\U0001F4F0 Latest", style={
                "color": COLORS["text"], "fontSize": "14px", "fontWeight": "600",
                "padding": "0 16px 8px", "margin": "0"
            }),
            html.Div(id="sidebar-articles", style={
                "maxHeight": "calc(100vh - 340px)", "overflowY": "auto", "padding": "0 12px 12px"
            }),
        ], className="sidebar"),

    ], className="main-area", style={"display": "flex", "padding": "0", "background": COLORS["background"], "height": "calc(100vh - 60px)"}),

    # Hidden active tab state
    dcc.Store(id='active-tab-store', data={'tab': 'd3'}),

    # Auto-refresh interval
    dcc.Interval(id="refresh-interval", interval=30000, n_intervals=0),



], style={
    "fontFamily": "Inter, sans-serif", "background": COLORS["background"],
    "minHeight": "100vh", "margin": "0", "padding": "0"
})

# =============================================================================
# CALLBACKS
# =============================================================================

# Inject CSS once
app.clientside_callback(
    """
    function() {
        if (!document.getElementById('gn-custom-css')) {
            var s = document.createElement('style');
            s.id = 'gn-custom-css';
            s.textContent = `
                #panel-d3, #panel-cyto, #panel-vis, #panel-sigma, #panel-ech, #panel-tv, #panel-cj, #panel-sig {
                    display: none;
                }
                #panel-d3.active, #panel-cyto.active, #panel-vis.active,
                #panel-sigma.active, #panel-ech.active, #panel-tv.active,
                #panel-cj.active, #panel-sig.active {
                    display: block;
                }
                .signal-card { background: #0a0e17; border-radius: 6px; padding: 10px; margin-bottom: 8px; border-left: 3px solid; }
                .signal-card.long { border-left-color: #00ff88; }
                .signal-card.short { border-left-color: #ff4757; }
                .signal-card.neutral { border-left-color: #888; }
                .article-item { padding: 8px 0; border-bottom: 1px solid rgba(255,215,0,0.07); }
                .article-item a { text-decoration: none; }
                .section-title { color: #ffd700; font-size: 14px; font-weight: 600; padding: 12px 16px 8px; }
                .empty-state { color: #888; font-size: 11px; padding: 10px 0; }
                .viz-container { position: relative; overflow: hidden; background: #0a0e17; }
                .viz-container svg { display: block; width: 100%; height: 100%; }
            `;
            document.head.appendChild(s);
        }
    }
    """,
    Output("css-injector", "children"),
    Input("refresh-interval", "n_intervals")
)

# Tab switching
@app.callback(
    [Output("tab-btn-d3", "className"),
     Output("tab-btn-cyto", "className"),
     Output("tab-btn-vis", "className"),
     Output("tab-btn-sigma", "className"),
     Output("tab-btn-ech", "className"),
     Output("tab-btn-tv", "className"),
     Output("tab-btn-cj", "className"),
     Output("tab-btn-sig", "className"),
     Output("panel-d3", "className"),
     Output("panel-cyto", "className"),
     Output("panel-vis", "className"),
     Output("panel-sigma", "className"),
     Output("panel-ech", "className"),
     Output("panel-tv", "className"),
     Output("panel-cj", "className"),
     Output("panel-sig", "className"),
     Output("active-tab-store", "data"),
    Output("gn-last-update", "children")],
    [Input("tab-btn-d3", "n_clicks"),
     Input("tab-btn-cyto", "n_clicks"),
     Input("tab-btn-vis", "n_clicks"),
     Input("tab-btn-sigma", "n_clicks"),
     Input("tab-btn-ech", "n_clicks"),
     Input("tab-btn-tv", "n_clicks"),
     Input("tab-btn-cj", "n_clicks"),
     Input("tab-btn-sig", "n_clicks")],
    [State("active-tab-store", "data")]
)
def switch_tab(n1, n2, n3, n4, n5, n6, n7, n8, current):
    from datetime import datetime
    ctx = dash.callback_context
    if not ctx.triggered:
        tab = current.get('tab', 'd3')
    else:
        tab = ctx.triggered[0]['prop_id'].split('.')[0].replace('tab-btn-', '')

    tab_map = {'d3': 'd3', 'cyto': 'cyto', 'vis': 'vis', 'sigma': 'sigma',
               'ech': 'ech', 'tv': 'tv', 'cj': 'cj', 'sig': 'sig'}

    current_tab = tab_map.get(tab, current.get('tab', 'd3'))

    def cls(t):
        return 'tab-btn active' if t == current_tab else 'tab-btn'
    def pcls(t):
        return 'viz-panel active' if t == current_tab else 'viz-panel'

    return [cls('d3'), cls('cyto'), cls('vis'), cls('sigma'),
            cls('ech'), cls('tv'), cls('cj'), cls('sig'),
            pcls('d3'), pcls('cyto'), pcls('vis'), pcls('sigma'),
            pcls('ech'), pcls('tv'), pcls('cj'), pcls('sig'),
            {'tab': current_tab},
            f"Updated: {datetime.now().strftime('%H:%M:%S')}"]

# Update sidebar signals
@app.callback(
    Output("sidebar-signals", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_sidebar_signals(n):
    signals = get_active_signals(limit=8)
    items = []
    for sig in signals:
        direction = sig.get('direction', 'neutral')
        conf = int(sig.get('confidence', 0) * 100)
        dir_color = COLORS['positive'] if direction == 'long' else COLORS['negative'] if direction == 'short' else COLORS['neutral']
        asset_color = ASSET_COLORS.get(sig.get('asset_class', 'multi'), COLORS['neutral'])
        card_class = 'long' if direction == 'long' else 'short' if direction == 'short' else 'neutral'

        items.append(html.A(
            html.Div([
                html.Div([
                    html.Span(direction.upper(), style={"color": dir_color, "fontWeight": "700", "fontSize": "10px"}),
                    html.Span(f" {sig.get('asset_class', '').upper()}", style={"color": asset_color, "fontWeight": "600", "fontSize": "10px"}),
                    html.Span(f" {conf}%", style={"color": COLORS['neutral'], "fontSize": "10px"}),
                ], style={"display": "flex", "justifyContent": "space-between"}),
                html.Div(sig.get('headline', '')[:60], style={
                    "color": COLORS['text'], "fontSize": "11px", "marginTop": "4px", "lineHeight": "1.3"}),
                html.Div(f"{sig.get('source_name', '')} \u2022 {sig.get('time_horizon', '')}", style={
                    "color": COLORS['neutral'], "fontSize": "9px", "marginTop": "4px"}),
            ], style={
                "background": COLORS['background'], "borderRadius": "6px", "padding": "10px", "marginBottom": "8px",
                "borderLeft": f"3px solid {dir_color}",
            }),
            href=sig.get('article_url', '#'),
            target="_blank",
            style={"textDecoration": "none"}
        ))

    if not items:
        items = [html.Div("No signals yet. Run ai_analyzer.py to generate signals.",
                          style={"color": COLORS["neutral"], "fontSize": "11px", "padding": "10px 0"})]
    return items

# Update sidebar articles
@app.callback(
    Output("sidebar-articles", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_sidebar_articles(n):
    articles = get_latest_articles(limit=20)
    items = []
    for art in articles:
        sentiment = art.get('sentiment_label', 'neutral')
        sent_color = COLORS['positive'] if sentiment == 'positive' else COLORS['negative'] if sentiment == 'negative' else COLORS['neutral']

        items.append(html.A(
            html.Div([
                html.Div(art.get('title', '')[:80] + ("..." if len(art.get('title', '')) > 80 else ''), style={
                    "color": COLORS['text'], "fontSize": "11px", "lineHeight": "1.3", "marginBottom": "4px"}),
                html.Div([
                    html.Span(art.get('source_name', '')[:15], style={"color": COLORS["primary"], "fontSize": "9px"}),
                    html.Span(f" \u2022 {sentiment}", style={"color": sent_color, "fontSize": "9px"}),
                ], style={"display": "flex", "gap": "6px"}),
            ], style={"padding": "8px 0", "borderBottom": f"1px solid {COLORS['primary']}11"}),
            href=art.get('url', '#'),
            target="_blank",
            style={"textDecoration": "none"}
        ))

    if not items:
        items = [html.Div("No articles yet. Run collector.py to fetch news.",
                          style={"color": COLORS["neutral"], "fontSize": "11px", "padding": "10px 0"})]
    return items

# Update signal feed panel (Tab 8)
@app.callback(
    Output("signal-feed-content", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_signal_feed(n):
    signals = get_active_signals(limit=20)
    if not signals:
        return [html.Div("No signals yet. Run ai_analyzer.py to generate signals.",
                         style={"color": COLORS["neutral"], "fontSize": "12px", "textAlign": "center", "padding": "40px"})]

    cards = []
    for sig in signals:
        direction = sig.get('direction', 'neutral')
        conf = int(sig.get('confidence', 0) * 100)
        dir_color = COLORS['positive'] if direction == 'long' else COLORS['negative'] if direction == 'short' else COLORS['neutral']
        asset_color = ASSET_COLORS.get(sig.get('asset_class', 'multi'), COLORS['neutral'])
        card_class = 'long' if direction == 'long' else 'short' if direction == 'short' else 'neutral'

        cards.append(html.Div(className=f"signal-card {card_class}", children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "6px"}, children=[
                html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center"}, children=[
                    html.Span(direction.upper(), style={"color": dir_color, "fontWeight": "700", "fontSize": "12px"}),
                    html.Span(sig.get('asset_class', '').upper(), style={"color": asset_color, "fontWeight": "600", "fontSize": "12px"}),
                ]),
                html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center"}, children=[
                    html.Span(f"{conf}%", style={"color": COLORS['neutral'], "fontSize": "11px"}),
                    html.Span(sig.get('time_horizon', ''), style={"color": COLORS['neutral'], "fontSize": "9px"}),
                ]),
            ]),
            html.Div(sig.get('headline', ''), style={
                "color": COLORS['text'], "fontSize": "12px", "lineHeight": "1.4", "marginBottom": "6px", "fontWeight": "500"}),
            html.Div(sig.get('rationale', ''), style={
                "color": COLORS['neutral'], "fontSize": "10px", "lineHeight": "1.4", "marginBottom": "6px"}),
            html.Div([
                html.Span(f"\uD83D\uDCC8 {sig.get('entry_price', 'current')}", style={"color": COLORS['accent'], "fontSize": "9px", "marginRight": "12px"}),
                html.Span(f"\uD83D\uDD3D {sig.get('stop_loss', 'N/A')}", style={"color": COLORS['negative'], "fontSize": "9px", "marginRight": "12px"}),
                html.Span(f"\uD83D\uDD3C {sig.get('exit_price', 'N/A')}", style={"color": COLORS['positive'], "fontSize": "9px"}),
            ], style={"marginBottom": "4px"}),
            html.Div(f"{sig.get('source_name', '')} | {sig.get('ai_model', '')}", style={
                "color": COLORS['neutral'], "fontSize": "9px"}),
        ]))

    return cards

# =============================================================================
# D3.js GRAPH - clientside callback (Tab 1)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        var container = document.getElementById('d3-graph-container');
        if (!container) return;

        // Inject CSS once
        if (!document.getElementById('gn-d3-css')) {
            var s = document.createElement('style');
            s.id = 'gn-d3-css';
            s.textContent = '#d3-graph-container{position:relative;overflow:hidden;background:#0a0e17}' +
                '#d3-graph-container svg{display:block;width:100%;height:100%}' +
                '#graph-tooltip{position:absolute;background:#1a1f2e;border:1px solid #ffd700;border-radius:8px;padding:12px;font-size:12px;max-width:340px;pointer-events:none;opacity:0;z-index:100;box-shadow:0 4px 20px rgba(0,0,0,0.5);font-family:Inter,sans-serif}' +
                '#graph-tooltip .tt-title{color:#e0e0e0;font-weight:600;font-size:12px}' +
                '#graph-tooltip .tt-meta{font-size:10px;color:#888;margin-top:6px}' +
                '#graph-tooltip .tt-keywords{font-size:10px;color:#00d4ff;margin-top:4px}' +
                '.node-group{cursor:pointer}' +
                '.node-label{pointer-events:none;font-family:Inter,sans-serif}';
            document.head.appendChild(s);
        }

        if (!window.gnGraphReady) {
            window.gnGraphReady = true;
            if (!window.d3) {
                var script = document.createElement('script');
                script.src = 'https://d3js.org/d3.v7.min.js';
                script.onload = function() { buildGraph(container); };
                document.head.appendChild(script);
            } else {
                buildGraph(container);
            }
        }
    }
    """,
    Output("d3-graph-container", "children"),
    Input("refresh-interval", "n_intervals")
)

# Embed the buildGraph function globally
app.clientside_callback(
    """
    function() {
        // The buildGraph function is defined globally via the script below
    }
    """,
    Output("d3-graph-container", "data"),
    Input("refresh-interval", "n_intervals")
)

# Inject buildGraph globally
app.clientside_callback(
    """
    function(n) {
        if (!document.getElementById('gn-buildgraph-def')) {
            var s = document.createElement('script');
            s.id = 'gn-buildgraph-def';
            s.textContent = """ + D3_BUILD_GRAPH_JS + """;
            document.head.appendChild(s);
        }
    }
    """,
    Output("d3-graph-container", "id"),
    Input("refresh-interval", "n_intervals")
)

# =============================================================================
# CYTOSCAPE.JS (Tab 2)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        if (!document.getElementById('gn-cyto-init')) {
            document.getElementById('gn-cyto-init').textContent = 'done';
            var s = document.createElement('script');
            s.src = 'https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js';
            s.onload = function() {
                var container = document.getElementById('cytoscape-container');
                if (!container) return;
                fetch('/api/graph-data')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (!data.nodes || !data.nodes.length) return;
                        var cyNodes = data.nodes.map(function(n) {
                            return { data: { id: ''+n.id, label: n.title.substring(0,20), color: n.color || '#888' }};
                        });
                        var cyEdges = (data.edges || []).map(function(e) {
                            return { data: { source: ''+e.source, target: ''+e.target, weight: e.strength }};
                        });
                        var cy = cytoscape({
                            container: container,
                            elements: cyNodes.concat(cyEdges),
                            style: [
                                { selector: 'node', style: { 'background-color': 'data(color)', 'label': 'data(label)', 'width': 20, 'height': 20, 'font-size': 8, 'color': '#e0e0e0', 'text-valign': 'bottom' }},
                                { selector: 'edge', style: { 'width': 1, 'line-color': 'rgba(255,215,0,0.3)', 'curve-style': 'haystack' }},
                            ],
                            layout: { name: 'cose', animate: false, padding: 10 }
                        });
                        cy.on('tap', 'node', function(e) {
                            var node = e.target;
                            var n = data.nodes.find(function(x) { return ''+x.id === node.id(); });
                            if (n && n.url) window.open(n.url, '_blank');
                        });
                    });
            };
            document.head.appendChild(s);
        }
    }
    """,
    Output("cytoscape-container", "children"),
    Input("refresh-interval", "n_intervals")
)

# =============================================================================
# VIS.JS (Tab 3)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        if (!document.getElementById('gn-visjs-init')) {
            var s = document.createElement('script');
            s.src = 'https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js';
            s.onload = function() {
                var container = document.getElementById('vis-container');
                if (!container) return;
                fetch('/api/graph-data')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (!data.nodes || !data.nodes.length) return;
                        var nodes = new vis.DataSet(data.nodes.map(function(n) {
                            return { id: n.id, label: n.title.substring(0,25), color: { background: n.color || '#888', border: '#ffd700' }, font: { color: '#e0e0e0', size: 10 }};
                        }));
                        var edges = new vis.DataSet((data.edges || []).map(function(e) {
                            return { from: e.source, to: e.target, value: e.strength, color: { color: 'rgba(255,215,0,0.3)' }};
                        }));
                        var options = { physics: { stabilization: { iterations: 100 } }, edges: { smooth: false } };
                        var network = new vis.Network(container, { nodes: nodes, edges: edges }, options);
                        network.on('click', function(e) {
                            if (e.nodes.length) {
                                var n = data.nodes.find(function(x) { return x.id === e.nodes[0]; });
                                if (n && n.url) window.open(n.url, '_blank');
                            }
                        });
                    });
            };
            document.head.appendChild(s);
            s.id = 'gn-visjs-init';
            document.head.appendChild(s);
        }
    }
    """,
    Output("vis-container", "children"),
    Input("refresh-interval", "n_intervals")
)

# =============================================================================
# SIGMA.JS (Tab 4)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        if (!document.getElementById('gn-sigma-init')) {
            var sigmaScript = document.createElement('script');
            sigmaScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/sigma.js/2.4.0/sigma.min.js';
            sigmaScript.onload = function() {
                var container = document.getElementById('sigma-container');
                if (!container) return;
                fetch('/api/graph-data')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (!data.nodes || !data.nodes.length) return;
                        var graph = { nodes: [], edges: [] };
                        data.nodes.forEach(function(n) {
                            graph.nodes.push({ id: ''+n.id, label: n.title.substring(0,20), color: n.color || '#888', size: n.is_signal ? 10 : 5 });
                        });
                        (data.edges || []).forEach(function(e) {
                            graph.edges.push({ id: 'e'+e.source+'-'+e.target, source: ''+e.source, target: ''+e.target, color: 'rgba(255,215,0,0.2)' });
                        });
                        var s = new sigma({ graph: graph, container: container, settings: { labelColor: '#e0e0e0', defaultNodeColor: '#888', defaultEdgeColor: 'rgba(255,215,0,0.2)', labelSize: 8 } });
                        s.refresh();
                    });
            };
            sigmaScript.id = 'gn-sigma-init';
            document.head.appendChild(sigmaScript);
        }
    }
    """,
    Output("sigma-container", "children"),
    Input("refresh-interval", "n_intervals")
)

# =============================================================================
# ECHARTS TIMELINE (Tab 5)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        if (!document.getElementById('gn-echarts-init')) {
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js';
            script.onload = function() {
                var container = document.getElementById('echarts-container');
                if (!container) return;
                fetch('/api/graph-data')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (!data.nodes || !data.nodes.length) return;
                        var chart = echarts.init(container, 'dark');
                        var pos = data.nodes.filter(function(n) { return n.sentiment === 'positive'; }).map(function(n) { return [data.nodes.indexOf(n), 1]; });
                        var neg = data.nodes.filter(function(n) { return n.sentiment === 'negative'; }).map(function(n) { return [data.nodes.indexOf(n), -1]; });
                        var option = {
                            backgroundColor: '#0a0e17',
                            title: { text: 'Sentiment Timeline', textStyle: { color: '#ffd700', fontSize: 14 }, left: 16, top: 8 },
                            tooltip: { trigger: 'axis', formatter: function(p) {
                                var idx = p[0].dataIndex;
                                var n = data.nodes[idx];
                                return n ? '<b>' + n.full_title.substring(0,60) + '</b><br/>' + n.source + ' | ' + n.sentiment : '';
                            }},
                            xAxis: { type: 'category', data: data.nodes.map(function(n) { return n.source.substring(0,10); }),
                                     axisLabel: { color: '#888', fontSize: 9 }, axisLine: { lineStyle: { color: '#ffd70022' } } },
                            yAxis: { type: 'value', max: 1.5, min: -1.5, splitLine: { lineStyle: { color: '#ffffff11' } },
                                      axisLabel: { color: '#888', formatter: function(v) { return v === 1 ? 'Positive' : v === -1 ? 'Negative' : ''; }}, },
                            series: [
                                { name: 'Positive', type: 'scatter', symbolSize: 12, data: pos, itemStyle: { color: '#00ff88' } },
                                { name: 'Negative', type: 'scatter', symbolSize: 12, data: neg, itemStyle: { color: '#ff4757' } },
                            ],
                            grid: { left: 50, right: 20, top: 40, bottom: 40 }
                        };
                        chart.setOption(option);
                        window.gnEcharts = chart;
                    });
            };
            script.id = 'gn-echarts-init';
            document.head.appendChild(script);
        } else if (window.gnEcharts) {
            window.gnEcharts.resize();
        }
    }
    """,
    Output("echarts-container", "children"),
    Input("refresh-interval", "n_intervals")
)

# =============================================================================
# TRADINGVIEW LIGHTWEIGHT CHARTS (Tab 6)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        if (!document.getElementById('gn-tv-init')) {
            var script = document.createElement('script');
            script.src = 'https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js';
            script.onload = function() {
                var container = document.getElementById('tradingview-container');
                if (!container) return;
                fetch('/api/signals')
                    .then(function(r) { return r.json(); })
                    .then(function(signals) {
                        if (!signals || !signals.length) return;
                        var chart = LightweightCharts.createChart(container, { width: container.clientWidth, height: container.clientHeight - 120, layout: { backgroundColor: '#0a0e17', textColor: '#e0e0e0' }, grid: { vertLines: { color: '#ffffff11' }, horzLines: { color: '#ffffff11' } } });
                        var series = chart.addLineSeries({ color: '#ffd700', lineWidth: 2 });
                        var points = signals.slice(0, 20).reverse().map(function(s, i) {
                            return { time: new Date(Date.now() - (signals.length - i) * 3600000).toISOString().split('T')[0], value: s.confidence * 100 };
                        });
                        series.setData(points);
                        chart.timeScale().fitContent();

                        // Signal markers
                        signals.slice(0, 10).forEach(function(s) {
                            var color = s.direction === 'long' ? '#00ff88' : s.direction === 'short' ? '#ff4757' : '#888';
                            var text = s.direction === 'long' ? '\u2191' : s.direction === 'short' ? '\u2193' : '\u2194';
                            series.createPriceLine({ price: s.confidence * 100, color: color, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: text });
                        });

                        window.gnTVChart = chart;

                        // HTML signal table below chart
                        var tableDiv = document.createElement('div');
                        tableDiv.style.cssText = 'height:100px;overflow-y:auto;padding:8px 16px';
                        var table = '<table style="width:100%;border-collapse:collapse;font-size:10px;color:#e0e0e0;font-family:Inter,sans-serif">' +
                            '<tr style="border-bottom:1px solid #ffd70022"><th style="text-align:left;padding:4px 8px;color:#ffd700">Dir</th><th style="text-align:left;padding:4px 8px;color:#ffd700">Asset</th><th style="text-align:right;padding:4px 8px;color:#ffd700">Conf%</th><th style="text-align:left;padding:4px 8px;color:#ffd700">Headline</th></tr>';
                        signals.slice(0, 10).forEach(function(s) {
                            var color = s.direction === 'long' ? '#00ff88' : s.direction === 'short' ? '#ff4757' : '#888';
                            table += '<tr style="border-bottom:1px solid #ffffff08"><td style="padding:4px 8px;color:' + color + ';font-weight:700">' + (s.direction || '').toUpperCase() + '</td>' +
                                '<td style="padding:4px 8px">' + (s.asset_class || '') + '</td>' +
                                '<td style="padding:4px 8px;text-align:right">' + Math.round((s.confidence || 0) * 100) + '%</td>' +
                                '<td style="padding:4px 8px">' + (s.headline || '').substring(0, 50) + '</td></tr>';
                        });
                        table += '</table>';
                        tableDiv.innerHTML = table;
                        container.appendChild(tableDiv);
                    });
            };
            script.id = 'gn-tv-init';
            document.head.appendChild(script);
        } else if (window.gnTVChart) {
            window.gnTVChart.resize();
        }
    }
    """,
    Output("tradingview-container", "children"),
    Input("refresh-interval", "n_intervals")
)

# =============================================================================
# CHART.JS (Tab 7)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        if (!document.getElementById('gn-cj-init')) {
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
            script.onload = function() {
                var container = document.getElementById('chartjs-container');
                if (!container) return;
                fetch('/api/signals')
                    .then(function(r) { return r.json(); })
                    .then(function(signals) {
                        if (!signals || !signals.length) return;

                        var canvas = document.createElement('canvas');
                        canvas.id = 'cj-canvas';
                        canvas.style.cssText = 'max-height:300px;padding:16px';
                        container.appendChild(canvas);

                        // Group by asset class
                        var assetMap = {};
                        signals.forEach(function(s) {
                            var a = s.asset_class || 'multi';
                            if (!assetMap[a]) assetMap[a] = [];
                            assetMap[a].push(s);
                        });

                        var labels = Object.keys(assetMap);
                        var longData = labels.map(function(a) { return assetMap[a].filter(function(s) { return s.direction === 'long'; }).length; });
                        var shortData = labels.map(function(a) { return assetMap[a].filter(function(s) { return s.direction === 'short'; }).length; });
                        var colors = labels.map(function(a) {
                            var c = { oil:'#ff6b35', gold:'#ffd700', stocks:'#00d4ff', crypto:'#ff9500', bonds:'#00ff88', forex:'#bf5af2', commodities:'#ff2d55', multi:'#888' };
                            return c[a] || '#888';
                        });

                        new Chart(canvas.getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: labels,
                                datasets: [
                                    { label: 'LONG', data: longData, backgroundColor: '#00ff88' },
                                    { label: 'SHORT', data: shortData, backgroundColor: '#ff4757' }
                                ]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: { title: { display: true, text: 'Signals by Asset Class', color: '#ffd700', font: { family: 'Inter' } }, legend: { labels: { color: '#e0e0e0' } } },
                                scales: { x: { ticks: { color: '#888' }, grid: { color: '#ffffff11' } }, y: { ticks: { color: '#888' }, grid: { color: '#ffffff11' } } }
                            }
                        });

                        // Signal table
                        var tableDiv = document.createElement('div');
                        tableDiv.style.cssText = 'max-height:200px;overflow-y:auto;padding:8px 16px';
                        var table = '<table style="width:100%;border-collapse:collapse;font-size:10px;color:#e0e0e0;font-family:Inter,sans-serif">' +
                            '<tr style="border-bottom:1px solid #ffd70022"><th style="text-align:left;padding:4px 8px;color:#ffd700">Dir</th><th style="text-align:right;padding:4px 8px;color:#ffd700">Conf%</th><th style="text-align:left;padding:4px 8px;color:#ffd700">Headline</th></tr>';
                        signals.slice(0, 15).forEach(function(s) {
                            var color = s.direction === 'long' ? '#00ff88' : s.direction === 'short' ? '#ff4757' : '#888';
                            table += '<tr style="border-bottom:1px solid #ffffff08"><td style="padding:4px 8px;color:' + color + ';font-weight:700">' + (s.direction || '').toUpperCase() + '</td>' +
                                '<td style="padding:4px 8px;text-align:right">' + Math.round((s.confidence || 0) * 100) + '%</td>' +
                                '<td style="padding:4px 8px">' + (s.headline || '').substring(0, 60) + '</td></tr>';
                        });
                        table += '</table>';
                        tableDiv.innerHTML = table;
                        container.appendChild(tableDiv);
                    });
            };
            script.id = 'gn-cj-init';
            document.head.appendChild(script);
        }
    }
    """,
    Output("chartjs-container", "children"),
    Input("refresh-interval", "n_intervals")
)

if __name__ == "__main__":
    print("\U0001F3C6 Golden News Dashboard - Multi-Viz Tabs")
    print("=" * 50)
    print("Dashboard: http://localhost:8050")
    print("Tabs: D3 | Cytoscape | Vis.js | Sigma | ECharts | TradingView | Chart.js | Signals")
    print("Sidebar: Original signals + articles feed")
    app.run(debug=False, host="0.0.0.0", port=8050)

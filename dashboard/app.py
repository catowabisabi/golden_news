#!/usr/bin/env python3
"""
Golden News Dashboard - Plotly Dash + D3.js
Real-time news graph visualization with trading signals
"""
import sqlite3
import json
from pathlib import Path
import dash
from dash import dcc, html, callback, Output, Input
import plotly.graph_objects as go
import plotly.express as px
from flask import Flask, jsonify

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

# Use Flask server for API endpoints
server = Flask(__name__)
app = dash.Dash(__name__, server=server, title="Golden News Dashboard")

@server.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

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

# Asset class colors for the graph
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
    """Build nodes and edges for D3.js force-directed graph"""
    articles = get_latest_articles(limit=40)
    signals = get_active_signals(limit=10)

    # Build keywords map
    db = get_db()
    keyword_map = {}
    for art in articles:
        cursor = db.execute("""
            SELECT keyword FROM article_keywords
            WHERE article_id = ? LIMIT 10
        """, (art["id"],))
        keywords = [row[0] for row in cursor.fetchall()]
        keyword_map[art["id"]] = keywords

        # Also extract keywords from title/summary
        text = f"{art['title']} {art.get('summary', '')}".lower()
        import re
        words = re.findall(r'\b\w{4,}\b', text)
        keyword_set = set(w for w in words if w not in ['that', 'this', 'with', 'from', 'have', 'been', 'were', 'they', 'what', 'when', 'where', 'which', 'about', 'would', 'could'])
        keyword_map[art["id"]].extend(list(keyword_set)[:5])

    db.close()

    # Build nodes
    nodes = []
    for i, art in enumerate(articles):
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

    # Build edges (articles sharing keywords)
    edges = []
    for i, art_a in enumerate(articles):
        for art_b in articles[i+1:]:
            kw_a = set(keyword_map.get(art_a["id"], []))
            kw_b = set(keyword_map.get(art_b["id"], []))
            shared = kw_a & kw_b

            if len(shared) >= 3:
                # Same source = stronger link
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

@server.route('/health')
def health():
    return jsonify({"status": "ok"})

@server.route('/api/graph-data')
def api_graph_data():
    """API endpoint for D3.js graph - returns JSON with nodes and edges"""
    data = get_graph_data()
    return jsonify(data)

@server.route('/api/signals')
def api_signals():
    """API endpoint for signals"""
    signals = get_active_signals(limit=20)
    return jsonify(signals)

@server.route('/api/articles')
def api_articles():
    """API endpoint for articles"""
    articles = get_latest_articles(limit=50)
    return jsonify(articles)

# Build the app layout
app.layout = html.Div([
    # Header - minimal, full width
    html.Div([
        html.H1("🏆 Golden News", style={
            "color": COLORS["primary"],
            "fontSize": "24px",
            "fontWeight": "700",
            "margin": "0",
            "fontFamily": "Inter, sans-serif"
        }),
        html.Div([
            html.Span("● LIVE", style={"color": COLORS["positive"], "fontSize": "12px", "fontWeight": "600", "marginRight": "20px"}),
            html.Span(id="last-update", style={"color": COLORS["neutral"], "fontSize": "12px"}),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "padding": "16px 24px",
        "background": COLORS["card_bg"],
        "borderBottom": f"1px solid {COLORS['primary']}22",
        "margin": "0"
    }),

    # Main content - full bleed, no margins
    html.Div([
        # Left: News Graph - full height D3.js embedded
        html.Div([
            html.Div(id="graph-container", style={
                "height": "calc(100vh - 60px)",
                "background": COLORS["background"],
                "margin": "0"
            }),
        ], style={
            "flex": "1",
            "background": COLORS["card_bg"],
            "margin": "0"
        }),

        # Right: Signals + Articles - compact sidebar
        html.Div([
            # Trading Signals
            html.H3("⚡ Signals", style={
                "color": COLORS["primary"],
                "fontSize": "14px",
                "fontWeight": "600",
                "padding": "12px 16px 8px",
                "margin": "0"
            }),
            html.Div(id="signals-container", style={
                "maxHeight": "200px",
                "overflowY": "auto",
                "padding": "0 12px"
            }),

            html.Hr(style={"borderColor": COLORS["primary"] + "22", "margin": "12px 0"}),

            # Latest Articles
            html.H3("📰 Latest", style={
                "color": COLORS["text"],
                "fontSize": "14px",
                "fontWeight": "600",
                "padding": "0 16px 8px",
                "margin": "0"
            }),
            html.Div(id="articles-container", style={
                "maxHeight": "calc(100vh - 340px)",
                "overflowY": "auto",
                "padding": "0 12px 12px"
            }),
        ], style={
            "width": "380px",
            "background": COLORS["card_bg"],
            "margin": "0",
            "borderLeft": f"1px solid {COLORS['primary']}11",
            "overflowY": "auto"
        }),
    ], style={
        "display": "flex",
        "padding": "0",
        "background": COLORS["background"],
        "height": "calc(100vh - 60px)"
    }),

    # Auto-refresh interval
    dcc.Interval(id="refresh-interval", interval=30000, n_intervals=0),


], style={
    "fontFamily": "Inter, sans-serif",
    "background": COLORS["background"],
    "minHeight": "100vh",
    "margin": "0",
    "padding": "0"
})

@callback(
    Output("signals-container", "children"),
    Output("articles-container", "children"),
    Output("last-update", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_dashboard(n):
    from datetime import datetime
    last_update = f"Updated: {datetime.now().strftime('%H:%M:%S')}"

    # Get data for sidebar
    signals = get_active_signals(limit=10)
    articles = get_latest_articles(limit=20)

    # Signals
    signals_html = []
    for sig in signals[:8]:
        direction_color = COLORS["positive"] if sig["direction"] == "long" else \
                          COLORS["negative"] if sig["direction"] == "short" else COLORS["neutral"]
        confidence_pct = int(sig["confidence"] * 100)

        signals_html.append(html.A(
            html.Div([
                html.Div([
                    html.Span(f"{sig['direction'].upper()}", style={
                        "color": direction_color,
                        "fontWeight": "700",
                        "fontSize": "10px"
                    }),
                    html.Span(f" {sig['asset_class'].upper()}", style={
                        "color": ASSET_COLORS.get(sig["asset_class"], COLORS["neutral"]),
                        "fontWeight": "600",
                        "fontSize": "10px"
                    }),
                    html.Span(f" {confidence_pct}%", style={
                        "color": COLORS["neutral"],
                        "fontSize": "10px"
                    }),
                ], style={"display": "flex", "justifyContent": "space-between"}),
                html.Div(sig["headline"], style={
                    "color": COLORS["text"],
                    "fontSize": "11px",
                    "marginTop": "4px",
                    "lineHeight": "1.3"
                }),
                html.Div(f"{sig.get('source_name', '')} • {sig.get('time_horizon', '')}", style={
                    "color": COLORS["neutral"],
                    "fontSize": "9px",
                    "marginTop": "4px"
                }),
            ], style={
                "background": COLORS["background"],
                "borderRadius": "6px",
                "padding": "10px",
                "marginBottom": "8px",
                "borderLeft": f"3px solid {direction_color}",
            }),
            href=f"https://www.google.com/search?q={sig.get('headline', '')}" if not sig.get('article_url') else sig.get('article_url'),
            target="_blank",
            style={"textDecoration": "none"}
        ))

    if not signals_html:
        signals_html = [html.Div("No signals yet. Run ai_analyzer.py to generate signals.",
                                 style={"color": COLORS["neutral"], "fontSize": "11px", "padding": "10px 0"})]

    # Articles
    articles_html = []
    for art in articles[:15]:
        sentiment_color = COLORS["positive"] if art["sentiment_label"] == "positive" else \
                         COLORS["negative"] if art["sentiment_label"] == "negative" else COLORS["neutral"]

        articles_html.append(html.A(
            html.Div([
                html.Div(art["title"][:80] + "..." if len(art["title"]) > 80 else art["title"], style={
                    "color": COLORS["text"],
                    "fontSize": "11px",
                    "lineHeight": "1.3",
                    "marginBottom": "4px"
                }),
                html.Div([
                    html.Span(art["source_name"][:15], style={"color": COLORS["primary"], "fontSize": "9px"}),
                    html.Span(f" • {art['sentiment_label']}", style={"color": sentiment_color, "fontSize": "9px"}),
                ], style={"display": "flex", "gap": "6px"}),
            ], style={"padding": "8px 0", "borderBottom": f"1px solid {COLORS['primary']}11"}),
            href=art["url"] if art["url"] else "#",
            target="_blank",
            style={"textDecoration": "none"}
        ))

    return signals_html, articles_html, last_update


def build_graph_script():
    """Returns a self-contained Dash clientside callback that builds the D3 graph."""
    return r"""
    function(n_intervals) {
        if (!document.getElementById('gn-graph-css')) {
            const style = document.createElement('style');
            style.id = 'gn-graph-css';
            style.textContent = `
                #graph-container { position: relative; overflow: hidden; }
                #graph-container svg { display: block; width: 100%; height: 100%; }
                #graph-tooltip {
                    position: absolute; background: #1a1f2e; border: 1px solid #ffd700;
                    border-radius: 8px; padding: 12px; font-size: 12px; max-width: 340px;
                    pointer-events: none; opacity: 0; z-index: 100;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.5); font-family: Inter, sans-serif;
                }
                #graph-tooltip .tt-title { color: #e0e0e0; font-weight: 600; font-size: 12px; }
                #graph-tooltip .tt-meta { font-size: 10px; color: #888; margin-top: 6px; }
                #graph-tooltip .tt-keywords { font-size: 10px; color: #00d4ff; margin-top: 4px; }
                .node-group { cursor: pointer; }
                .node-label { pointer-events: none; font-family: Inter, sans-serif; }
            `;
            document.head.appendChild(style);
        }

        const container = document.getElementById('graph-container');
        if (!container) return null;

        function buildGraph(container) {
        const width  = container.clientWidth  || window.innerWidth  - 380;
        const height = container.clientHeight || window.innerHeight - 60;

        // ---- SVG ----
        const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svgEl.setAttribute('width', width);
        svgEl.setAttribute('height', height);
        svgEl.style.background = '#0a0e17';
        container.appendChild(svgEl);
        const svg = d3.select(svgEl);
        const g   = svg.append('g');

        // ---- Tooltip (HTML div, NOT inside SVG) ----
        const tooltip = document.createElement('div');
        tooltip.id = 'graph-tooltip';
        tooltip.innerHTML = '<div class="tt-title"></div><div class="tt-meta"></div><div class="tt-keywords"></div>';
        container.appendChild(tooltip);

        // ---- Zoom ----
        const zoom = d3.zoom()
            .scaleExtent([0.2, 4])
            .on('zoom', e => g.attr('transform', e.transform));
        svg.call(zoom);

        // ---- Controls panel (HTML overlay) ----
        const ctrl = document.createElement('div');
        ctrl.style.cssText = 'position:absolute;top:16px;left:16px;background:rgba(26,31,46,0.95);border-radius:8px;padding:12px 16px;font-size:11px;z-index:10;border:1px solid rgba(255,215,0,0.2);font-family:Inter,sans-serif;';
        ctrl.innerHTML = `
            <div style="margin-bottom:8px">
                <span style="color:#ffd700;font-weight:600">Nodes:</span>
                <input type="range" id="gn-node-slider" min="5" max="40" value="15"
                    style="width:90px;accent-color:#ffd700;margin:0 8px">
                <span id="gn-node-count" style="color:#e0e0e0;min-width:20px;display:inline-block">15</span>
            </div>
            <div>
                <button id="gn-reset-btn" class="gn-control-btn"
                    style="background:rgba(255,215,0,0.15);border:1px solid rgba(255,215,0,0.4);color:#ffd700;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:10px">Reset</button>
                <button id="gn-labels-btn" class="gn-control-btn"
                    style="background:rgba(255,215,0,0.15);border:1px solid rgba(255,215,0,0.4);color:#ffd700;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:10px;margin-left:8px">Labels</button>
            </div>`;
        container.appendChild(ctrl);

        document.getElementById('gn-reset-btn').onclick = () =>
            svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
        document.getElementById('gn-labels-btn').onclick = () => {
            window.gnShowLabels = !window.gnShowLabels;
            svg.selectAll('.node-label').style('opacity', window.gnShowLabels ? 1 : 0);
        };
        const slider = document.getElementById('gn-node-slider');
        slider.addEventListener('input', function() {
            document.getElementById('gn-node-count').textContent = this.value;
            window.gnNodeLimit = +this.value;
            svg.selectAll('.node-group').style('display',
                (d, i) => i < window.gnNodeLimit ? 'block' : 'none');
        });

        // ---- Stats text (SVG) ----
        const statsText = svg.append('text')
            .attr('id', 'gn-stats')
            .attr('x', width - 20).attr('y', height - 20)
            .attr('text-anchor', 'end')
            .attr('fill', '#888').attr('font-size', '10px')
            .attr('font-family', 'Inter, sans-serif')
            .text('Loading...');

        // ---- Legend (SVG) ----
        const legend = svg.append('g')
            .attr('transform', `translate(16,${height - 105})`);
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
        ].forEach((item, i) => {
            const y = 34 + i * 15;
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

        // ---- Fetch & Render ----
        function renderGraph() {
            fetch('/api/graph-data')
                .then(r => r.ok ? r.json() : Promise.reject(new Error('API ' + r.status)))
                .then(data => {
                    if (!data.nodes || data.nodes.length === 0) {
                        svg.append('text').attr('x', width/2).attr('y', height/2)
                            .attr('fill', '#888').attr('text-anchor', 'middle')
                            .attr('font-family', 'Inter, sans-serif')
                            .text('No articles yet. Run collector.py to fetch news.');
                        return;
                    }

                    statsText.text(`${data.nodes.length} articles | ${data.edges ? data.edges.length : 0} connections`);

                    // Random initial positions
                    const nodes = data.nodes.map(n => ({
                        ...n,
                        x: width/2  + (Math.random() - 0.5) * Math.min(width * 0.4, 400),
                        y: height/2 + (Math.random() - 0.5) * Math.min(height * 0.4, 300)
                    }));
                    const nodeMap = new Map(nodes.map(n => [n.id, n]));
                    window.gnNodes   = nodes;
                    window.gnNodeMap = nodeMap;

                    const links = (data.edges || []).map(e => ({
                        source: nodeMap.get(e.source),
                        target: nodeMap.get(e.target),
                        strength: e.strength,
                        shared:   e.shared_keywords || []
                    })).filter(e => e.source && e.target);
                    window.gnLinks = links;

                    // Simulation
                    const sim = d3.forceSimulation(nodes)
                        .force('link',      d3.forceLink(links).id(d => d.id).distance(d => 150 - d.strength * 50))
                        .force('charge',     d3.forceManyBody().strength(-350))
                        .force('center',     d3.forceCenter(width/2, height/2))
                        .force('collision',  d3.forceCollide().radius(d => (d.is_signal ? 18 : 10) + 25));
                    window.gnSim = sim;

                    // Links
                    const link = g.append('g').attr('class', 'links')
                        .selectAll('line').data(links).enter()
                        .append('line')
                        .attr('stroke', d => `rgba(255,215,0,${Math.max(d.strength * 0.6, 0.1)})`)
                        .attr('stroke-width', d => Math.max(d.strength * 2, 0.5));

                    // Nodes
                    const node = g.append('g').attr('class', 'nodes')
                        .selectAll('g').data(nodes).enter()
                        .append('g').attr('class', 'node-group')
                        .call(d3.drag()
                            .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                            .on('drag',   (e, d) => { d.fx = e.x; d.fy = e.y; })
                            .on('end',    (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
                        );

                    node.append('circle')
                        .attr('r', d => d.is_signal ? 16 : 8)
                        .attr('fill', d => d.color || '#888')
                        .attr('stroke', d => d.is_signal ? '#ffd700' : 'transparent')
                        .attr('stroke-width', d => d.is_signal ? 3 : 0);

                    node.append('text').attr('class', 'node-label')
                        .text(d => {
                            const t = d.full_title || d.title || '';
                            const w = t.split(' ').slice(0, 4);
                            return w.join(' ') + (t.split(' ').length > 4 ? '...' : '');
                        })
                        .attr('dy',      d => d.is_signal ? 24 : 18)
                        .attr('text-anchor', 'middle')
                        .attr('fill', '#e0e0e0').attr('font-size', '8px')
                        .attr('font-family', 'Inter, sans-serif')
                        .style('pointer-events', 'none');

                    // Mouse events (use page coordinates for tooltip positioning)
                    node.on('mouseover', (e, d) => {
                        tooltip.querySelector('.tt-title').textContent = d.full_title || d.title || '';
                        tooltip.querySelector('.tt-meta').textContent = `${d.source || ''} | ${d.sentiment || ''}`;
                        tooltip.querySelector('.tt-keywords').textContent = '\uD83D\uDD17 ' + ((d.keywords || []).slice(0, 5)).join(', ');
                        tooltip.style.opacity = 1;
                    })
                    .on('mousemove', (e) => {
                        const rect = container.getBoundingClientRect();
                        tooltip.style.left = (e.clientX - rect.left + 15) + 'px';
                        tooltip.style.top  = (e.clientY - rect.top  - 10) + 'px';
                    })
                    .on('mouseout',  () => { tooltip.style.opacity = 0; })
                    .on('click', (e, d) => { if (d.url) window.open(d.url, '_blank'); });

                    // Tick
                    sim.on('tick', () => {
                        link.attr('x1', d => d.source.x)
                            .attr('y1', d => d.source.y)
                            .attr('x2', d => d.target.x)
                            .attr('y2', d => d.target.y);
                        node.attr('transform', d => {
                            d.x = Math.max(30, Math.min(width  - 30, d.x));
                            d.y = Math.max(30, Math.min(height - 30, d.y));
                            return `translate(${d.x},${d.y})`;
                        });
                    });
                })
                .catch(err => {
                    console.error('Graph error:', err);
                    svg.append('text').attr('x', width/2).attr('y', height/2)
                        .attr('fill', '#ff4757').attr('text-anchor', 'middle')
                        .text('Error: ' + err.message);
                });
        }

        renderGraph();

        // Auto-refresh every 30s WITHOUT destroying/recreating SVG
        window.gnRefreshTimer = setInterval(() => {
            if (!window.gnSim) return;
            fetch('/api/graph-data')
                .then(r => r.ok ? r.json() : Promise.reject())
                .then(data => {
                    if (!data || !data.nodes || !data.nodes.length) return;
                    statsText.text(`${data.nodes.length} articles | ${data.edges ? data.edges.length : 0} connections`);
                    // Merge update: only refresh node colors/signal state, keep positions
                    data.nodes.forEach(n => {
                        const ex = window.gnNodeMap.get(n.id);
                        if (ex) {
                            ex.color      = n.color;
                            ex.is_signal  = n.is_signal;
                            ex.keywords   = n.keywords;
                            ex.full_title = n.full_title;
                            ex.source     = n.source;
                            ex.sentiment  = n.sentiment;
                        }
                    });
                    // Restart sim gently
                    window.gnSim.alpha(0.1).restart();
                }).catch(() => {});
        }, 30000);
        }  // end buildGraph

        if (!window.gnGraphReady) {
            window.gnGraphReady = true;
            if (!window.d3) {
                const script = document.createElement('script');
                script.src = 'https://d3js.org/d3.v7.min.js';
                script.onload = () => buildGraph(container);
                document.head.appendChild(script);
            } else {
                buildGraph(container);
            }
        }
        return null;
    }  // end callback
    """


_buildGraphJS = build_graph_script()

app.clientside_callback(
    _buildGraphJS,
    Output("graph-container", "children"),
    Input("refresh-interval", "n_intervals")
)


if __name__ == "__main__":
    print("🌐 Starting Golden News Dashboard...")
    print("📊 Dashboard: http://localhost:8050")
    print("📡 WebSocket: ws://localhost:8765")
    app.run(debug=False, host="0.0.0.0", port=8050)

#!/usr/bin/env python3
"""
Golden News Dashboard - Plotly Dash + Multiple Visualization Libraries
Real-time news graph visualization with trading signals
8 Tabs: D3 Force Graph, Cytoscape.js, Vis.js, Sigma.js, ECharts, TradingView, Chart.js, Signal Feed
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
    """Build nodes and edges for force-directed graph"""
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

@server.route('/api/graph-data')
def api_graph_data():
    """API endpoint for D3.js graph - returns JSON with nodes and edges"""
    data = get_graph_data()
    return jsonify(data, ensure_ascii=False)

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

# =============================================================================
# DASH APP LAYOUT - TABBED DASHBOARD
# =============================================================================

# Tab definitions with icons
TAB_CONFIG = [
    {"id": "tab-d3", "label": "D3 Force", "icon": "🔮"},
    {"id": "tab-cytoscape", "label": "Cytoscape", "icon": "🕸️"},
    {"id": "tab-vis", "label": "Vis.js", "icon": "🌐"},
    {"id": "tab-sigma", "label": "Sigma.js", "icon": "Σ"},
    {"id": "tab-echarts", "label": "ECharts", "icon": "📊"},
    {"id": "tab-tradingview", "label": "TradingView", "icon": "📈"},
    {"id": "tab-chartjs", "label": "Chart.js", "icon": "📉"},
    {"id": "tab-signals", "label": "Signal Feed", "icon": "⚡"},
]

app.layout = html.Div([
    # Header
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

    # Tab Navigation
    html.Div([
        html.Div([
            dcc.Tabs(id="viz-tabs", value="tab-d3", children=[
                dcc.Tab(
                    label=f"{cfg['icon']} {cfg['label']}",
                    value=cfg["id"],
                    style={
                        "backgroundColor": COLORS["background"],
                        "color": COLORS["neutral"],
                        "border": "none",
                        "padding": "12px 20px",
                        "fontSize": "13px",
                        "fontWeight": "500",
                    },
                    selected_style={
                        "backgroundColor": COLORS["card_bg"],
                        "color": COLORS["primary"],
                        "border": "none",
                        "borderBottom": f"2px solid {COLORS['primary']}",
                        "padding": "12px 20px",
                        "fontSize": "13px",
                        "fontWeight": "600",
                    }
                ) for cfg in TAB_CONFIG
            ]),
        ], style={"margin": "0", "padding": "0 16px"}),
    ], style={
        "background": COLORS["background"],
        "borderBottom": f"1px solid {COLORS['primary']}22",
    }),

    # Tab Content Container
    html.Div(id="tab-content", style={
        "height": "calc(100vh - 120px)",
        "overflow": "auto",
        "background": COLORS["background"],
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


# =============================================================================
# TAB CONTENT RENDERER
# =============================================================================

@callback(
    Output("tab-content", "children"),
    Input("viz-tabs", "value"),
    Input("refresh-interval", "n_intervals")
)
def render_tab(tab_id, n_intervals):
    """Render content for each tab"""
    
    if tab_id == "tab-d3":
        return html.Div([
            # Controls
            html.Div([
                html.Span("Nodes:", style={"color": COLORS["text"], "fontSize": "12px", "marginRight": "8px"}),
                dcc.Slider(id="d3-node-slider", min=5, max=40, value=15, step=1,
                           tooltip={"placement": "bottom", "always_visible": False},
                           style={"width": "200px", "display": "inline-block"}),
                html.Button("Reset View", id="d3-reset-btn", n_clicks=0,
                           style={"background": f"rgba(255,215,0,0.15)", "border": f"1px solid {COLORS['primary']}66",
                                  "color": COLORS["primary"], "padding": "6px 12px", "borderRadius": "4px",
                                  "cursor": "pointer", "fontSize": "11px", "marginLeft": "16px"}),
                html.Button("Toggle Labels", id="d3-labels-btn", n_clicks=0,
                           style={"background": f"rgba(255,215,0,0.15)", "border": f"1px solid {COLORS['primary']}66",
                                  "color": COLORS["primary"], "padding": "6px 12px", "borderRadius": "4px",
                                  "cursor": "pointer", "fontSize": "11px", "marginLeft": "8px"}),
            ], style={"padding": "12px 16px", "background": COLORS["card_bg"],
                      "display": "flex", "alignItems": "center", "gap": "8px"}),
            
            # D3 Graph Container
            html.Div(id="graph-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
                "margin": "0"
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-cytoscape":
        return html.Div([
            html.Div("Cytoscape.js Network Graph", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="cytoscape-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-vis":
        return html.Div([
            html.Div("Vis.js Network Graph", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="vis-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-sigma":
        return html.Div([
            html.Div("Sigma.js Graph", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="sigma-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-echarts":
        return html.Div([
            html.Div("ECharts Timeline", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="echarts-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-tradingview":
        return html.Div([
            html.Div("TradingView Lightweight Charts", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="tradingview-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-chartjs":
        return html.Div([
            html.Div("Chart.js Analytics", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="chartjs-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
            }),
        ], style={"height": "100%"})
    
    elif tab_id == "tab-signals":
        return html.Div([
            html.Div("⚡ Trading Signal Feed", style={
                "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600",
                "padding": "16px", "borderBottom": f"1px solid {COLORS['primary']}22"
            }),
            html.Div(id="signal-feed-container", style={
                "height": "calc(100vh - 180px)",
                "background": COLORS["background"],
                "overflow": "auto",
                "padding": "16px",
            }),
        ], style={"height": "100%"})
    
    return html.Div("Select a tab", style={"color": COLORS["text"], "padding": "20px"})


# =============================================================================
# D3 FORCE GRAPH (TAB 1) - Existing functionality preserved
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        // Inject CSS once
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
                .gn-control-btn { cursor: pointer; }
            `;
            document.head.appendChild(style);
        }

        const containerId = 'graph-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        // Initialize graph only once
        if (!window.gnGraphReady) {
            window.gnGraphReady = true;

            // Load D3.js dynamically
            if (!window.d3) {
                const script = document.createElement('script');
                script.src = 'https://d3js.org/d3.v7.min.js';
                script.onload = () => buildGraph(container);
                document.head.appendChild(script);
            } else {
                buildGraph(container);
            }
        }
        // Return null to prevent Dash from clearing our D3-managed children
        return null;
    }
    """,
    Output("graph-container", "children"),
    Input("refresh-interval", "n_intervals")
)


def build_graph_script():
    """Returns the JavaScript string for the buildGraph function."""
    return r"""
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

                    // Mouse events
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
    }
    """

_buildGraphJS = build_graph_script()

app.clientside_callback(
    _buildGraphJS,
    Output("graph-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# CYTOSCAPE.JS TAB (TAB 2)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        const containerId = 'cytoscape-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!window.gnCytoscapeReady) {
            window.gnCytoscapeReady = true;

            // Load Cytoscape.js
            if (!window.cytoscape) {
                const script = document.createElement('script');
                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js';
                script.onload = () => initCytoscape(container);
                document.head.appendChild(script);
            } else {
                initCytoscape(container);
            }
        }
        return null;
    }

    function initCytoscape(container) {
        container.innerHTML = '';

        const style = document.createElement('style');
        style.textContent = `
            #cytoscape-container { width: 100%; height: 100%; }
        `;
        container.appendChild(style);

        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div style="color:#888;text-align:center;padding:40px;font-family:Inter,sans-serif">No articles yet. Run collector.py to fetch news.</div>';
                    return;
                }

                const elements = [];
                data.nodes.forEach(n => {
                    elements.push({
                        data: { id: n.id, label: n.title.substring(0, 30), color: n.color, full_title: n.full_title, source: n.source, sentiment: n.sentiment }
                    });
                });
                data.edges.forEach(e => {
                    elements.push({
                        data: { source: e.source, target: e.target, strength: e.strength }
                    });
                });

                const cy = cytoscape({
                    container: container,
                    elements: elements,
                    style: [
                        {
                            selector: 'node',
                            style: {
                                'background-color': 'data(color)',
                                'label': 'data(label)',
                                'color': '#e0e0e0',
                                'font-size': '8px',
                                'font-family': 'Inter, sans-serif',
                                'text-valign': 'bottom',
                                'text-margin-y': 4,
                                'width': 12,
                                'height': 12
                            }
                        },
                        {
                            selector: 'edge',
                            style: {
                                'width': 1,
                                'line-color': 'rgba(255,215,0,0.3)',
                                'curve-style': 'bezier'
                            }
                        }
                    ],
                    layout: { name: 'cose', animate: true, animationDuration: 1000 },
                    wheelSensitivity: 0.3,
                    minZoom: 0.3,
                    maxZoom: 3
                });

                cy.on('tap', 'node', function(evt) {
                    const node = evt.target;
                    alert('Title: ' + node.data('full_title') + '\\nSource: ' + node.data('source') + '\\nSentiment: ' + node.data('sentiment'));
                });
            })
            .catch(err => {
                container.innerHTML = '<div style="color:#ff4757;text-align:center;padding:40px;font-family:Inter,sans-serif">Error: ' + err.message + '</div>';
            });
    }
    """,
    Output("cytoscape-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# VIS.JS TAB (TAB 3)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        const containerId = 'vis-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!window.gnVisReady) {
            window.gnVisReady = true;

            // Load Vis.js
            if (!window.vis) {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = 'https://unpkg.com/vis-network/standalone/umd/vis-network.min.css';
                document.head.appendChild(link);

                const script = document.createElement('script');
                script.src = 'https://unpkg.com/vis-network/standalone/umd/vis-network.min.js';
                script.onload = () => initVis(container);
                document.head.appendChild(script);
            } else {
                initVis(container);
            }
        }
        return null;
    }

    function initVis(container) {
        container.innerHTML = '';

        const style = document.createElement('style');
        style.textContent = `
            #vis-container { width: 100%; height: 100%; }
        `;
        container.appendChild(style);

        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div style="color:#888;text-align:center;padding:40px;font-family:Inter,sans-serif">No articles yet. Run collector.py to fetch news.</div>';
                    return;
                }

                const nodes = new vis.DataSet(data.nodes.map(n => ({
                    id: n.id,
                    label: n.title.substring(0, 25),
                    color: { background: n.color, border: n.is_signal ? '#ffd700' : n.color, highlight: { background: '#00d4ff' } },
                    font: { color: '#e0e0e0', size: 10, face: 'Inter' },
                    title: n.full_title + '\\n' + n.source,
                    size: n.is_signal ? 16 : 10
                })));

                const edges = new vis.DataSet(data.edges.map(e => ({
                    from: e.source,
                    to: e.target,
                    value: e.strength,
                    color: { color: 'rgba(255,215,0,0.4)' },
                    smooth: { type: 'continuous' }
                })));

                const networkData = { nodes: nodes, edges: edges };
                const options = {
                    physics: { stabilization: { iterations: 200 }, barnesHut: { gravitationalConstant: -2000 } },
                    interaction: { hover: true, tooltipDelay: 200 },
                    nodes: { borderWidth: 2 },
                    edges: { width: 1 }
                };

                const network = new vis.Network(container, networkData, options);

                network.on('click', function(params) {
                    if (params.nodes.length > 0) {
                        const nodeId = params.nodes[0];
                        const node = data.nodes.find(n => n.id === nodeId);
                        if (node) alert(node.full_title + '\\n\\nSource: ' + node.source);
                    }
                });
            })
            .catch(err => {
                container.innerHTML = '<div style="color:#ff4757;text-align:center;padding:40px;font-family:Inter,sans-serif">Error: ' + err.message + '</div>';
            });
    }
    """,
    Output("vis-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# SIGMA.JS TAB (TAB 4)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        const containerId = 'sigma-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!window.gnSigmaReady) {
            window.gnSigmaReady = true;

            // Load Sigma.js
            if (!window.Sigma) {
                const script = document.createElement('script');
                script.src = 'https://unpkg.com/sigma@1.2.1/build/sigma.min.js';
                script.onload = () => {
                    const gephiScript = document.createElement('script');
                    gephiScript.src = 'https://unpkg.com/sigma@1.2.1/plugins/sigma.plugins.gephi.js';
                    gephiScript.onload = () => initSigma(container);
                    document.head.appendChild(gephiScript);
                };
                document.head.appendChild(script);
            } else {
                initSigma(container);
            }
        }
        return null;
    }

    function initSigma(container) {
        container.innerHTML = '';

        const style = document.createElement('style');
        style.textContent = `
            #sigma-container { width: 100%; height: 100%; }
        `;
        container.appendChild(style);

        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div style="color:#888;text-align:center;padding:40px;font-family:Inter,sans-serif">No articles yet. Run collector.py to fetch news.</div>';
                    return;
                }

                const graph = { nodes: [], edges: [] };

                data.nodes.forEach(n => {
                    graph.nodes.push({
                        id: 'n' + n.id,
                        label: n.title.substring(0, 20),
                        x: Math.random() * 100,
                        y: Math.random() * 100,
                        size: n.is_signal ? 10 : 5,
                        color: n.color,
                        fullTitle: n.full_title,
                        source: n.source
                    });
                });

                data.edges.forEach(e => {
                    graph.edges.push({
                        id: 'e' + e.source + '-' + e.target,
                        source: 'n' + e.source,
                        target: 'n' + e.target,
                        color: 'rgba(255,215,0,0.3)',
                        size: e.strength * 2
                    });
                });

                const sigmaInstance = new Sigma(graph, container, {
                    font: 'Inter, sans-serif',
                    labelColor: '#e0e0e0',
                    labelSize: 10,
                    defaultNodeColor: '#888',
                    defaultEdgeColor: 'rgba(255,215,0,0.3)',
                    labelThreshold: 8
                });

                sigmaInstance.bind('clickNode', function(e) {
                    alert(e.data.node.fullTitle + '\\nSource: ' + e.data.node.source);
                });
            })
            .catch(err => {
                container.innerHTML = '<div style="color:#ff4757;text-align:center;padding:40px;font-family:Inter,sans-serif">Error: ' + err.message + '</div>';
            });
    }
    """,
    Output("sigma-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# ECHARTS TIMELINE TAB (TAB 5)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        const containerId = 'echarts-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!window.gnEchartsReady) {
            window.gnEchartsReady = true;

            // Load ECharts
            if (!window.echarts) {
                const script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js';
                script.onload = () => initEcharts(container);
                document.head.appendChild(script);
            } else {
                initEcharts(container);
            }
        }
        return null;
    }

    function initEcharts(container) {
        container.innerHTML = '';

        const chartDiv = document.createElement('div');
        chartDiv.style.width = '100%';
        chartDiv.style.height = '100%';
        container.appendChild(chartDiv);

        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div style="color:#888;text-align:center;padding:40px;font-family:Inter,sans-serif">No articles yet. Run collector.py to fetch news.</div>';
                    return;
                }

                // Group articles by day for timeline
                const timeline = {};
                data.nodes.forEach(n => {
                    const date = n.published ? n.published.split('T')[0] : 'Unknown';
                    if (!timeline[date]) timeline[date] = { positive: 0, negative: 0, neutral: 0, total: 0 };
                    timeline[date][n.sentiment]++;
                    timeline[date].total++;
                });

                const dates = Object.keys(timeline).sort();
                const positiveData = dates.map(d => timeline[d].positive);
                const negativeData = dates.map(d => timeline[d].negative);
                const neutralData = dates.map(d => timeline[d].neutral);
                const totalData = dates.map(d => timeline[d].total);

                const chart = echarts.init(chartDiv);
                const option = {
                    backgroundColor: '#0a0e17',
                    tooltip: { trigger: 'axis', backgroundColor: '#1a1f2e', borderColor: '#ffd700', textStyle: { color: '#e0e0e0' } },
                    legend: { data: ['Positive', 'Negative', 'Neutral'], textStyle: { color: '#e0e0e0', fontFamily: 'Inter' }, top: 20 },
                    grid: { left: 50, right: 30, top: 60, bottom: 60 },
                    xAxis: { type: 'category', data: dates, axisLabel: { color: '#888', fontFamily: 'Inter' }, axisLine: { lineStyle: { color: '#ffd70044' } } },
                    yAxis: { type: 'value', axisLabel: { color: '#888', fontFamily: 'Inter' }, splitLine: { lineStyle: { color: '#ffffff11' } } },
                    series: [
                        { name: 'Positive', type: 'line', smooth: true, data: positiveData, itemStyle: { color: '#00ff88' }, areaStyle: { color: 'rgba(0,255,136,0.1)' } },
                        { name: 'Negative', type: 'line', smooth: true, data: negativeData, itemStyle: { color: '#ff4757' }, areaStyle: { color: 'rgba(255,71,87,0.1)' } },
                        { name: 'Neutral', type: 'line', smooth: true, data: neutralData, itemStyle: { color: '#888' }, areaStyle: { color: 'rgba(136,136,136,0.1)' } }
                    ],
                    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { type: 'slider', backgroundColor: '#1a1f2e', fillerColor: 'rgba(255,215,0,0.2)', handleStyle: { color: '#ffd700' } }]
                };
                chart.setOption(option);

                window.gnEchartsChart = chart;
            })
            .catch(err => {
                container.innerHTML = '<div style="color:#ff4757;text-align:center;padding:40px;font-family:Inter,sans-serif">Error: ' + err.message + '</div>';
            });
    }
    """,
    Output("echarts-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# TRADINGVIEW LIGHTWEIGHT CHARTS TAB (TAB 6)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        const containerId = 'tradingview-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!window.gnTvReady) {
            window.gnTvReady = true;

            // Load TradingView Lightweight Charts
            if (!window.LightweightCharts) {
                const script = document.createElement('script');
                script.src = 'https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js';
                script.onload = () => initTradingView(container);
                document.head.appendChild(script);
            } else {
                initTradingView(container);
            }
        }
        return null;
    }

    function initTradingView(container) {
        container.innerHTML = '';

        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;';

        const chartContainer = document.createElement('div');
        chartContainer.style.cssText = 'width:90%;height:60%;max-width:1200px;';
        wrapper.appendChild(chartContainer);

        const infoDiv = document.createElement('div');
        infoDiv.style.cssText = 'color:#888;font-family:Inter,sans-serif;font-size:12px;margin-top:20px;text-align:center;';
        infoDiv.textContent = 'TradingView Lightweight Charts - Signal Sentiment Over Time';
        wrapper.appendChild(infoDiv);

        container.appendChild(wrapper);

        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div style="color:#888;text-align:center;padding:40px;font-family:Inter,sans-serif">No articles yet. Run collector.py to fetch news.</div>';
                    return;
                }

                // Aggregate sentiment by hour
                const hourlySentiment = {};
                data.nodes.forEach(n => {
                    const hour = n.published ? n.published.substring(0, 13) + ':00:00' : 'unknown';
                    if (!hourlySentiment[hour]) hourlySentiment[hour] = { positive: 0, negative: 0, neutral: 0 };
                    hourlySentiment[hour][n.sentiment]++;
                });

                const timestamps = Object.keys(hourlySentiment).sort();
                const positiveCandles = timestamps.map(h => ({ time: h.replace(/[-:]/g, '').substring(0, 8) + 'T' + h.substring(9, 17).replace(':', '') + 'Z', value: hourlySentiment[h].positive }));
                const negativeCandles = timestamps.map(h => ({ time: h.replace(/[-:]/g, '').substring(0, 8) + 'T' + h.substring(9, 17).replace(':', '') + 'Z', value: hourlySentiment[h].negative }));
                const neutralCandles = timestamps.map(h => ({ time: h.replace(/[-:]/g, '').substring(0, 8) + 'T' + h.substring(9, 17).replace(':', '') + 'Z', value: hourlySentiment[h].neutral }));

                const chart = LightweightCharts.createChart(chartContainer, {
                    layout: { background: { type: 'solid', color: '#0a0e17' }, textColor: '#e0e0e0' },
                    grid: { vertLines: { color: '#ffffff11' }, horzLines: { color: '#ffffff11' } },
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight
                });

                const positiveSeries = chart.addLineSeries({ color: '#00ff88', lineWidth: 2, title: 'Positive' });
                positiveSeries.setData(positiveCandles);

                const negativeSeries = chart.addLineSeries({ color: '#ff4757', lineWidth: 2, title: 'Negative' });
                negativeSeries.setData(negativeCandles);

                const neutralSeries = chart.addLineSeries({ color: '#888', lineWidth: 2, title: 'Neutral' });
                neutralSeries.setData(neutralCandles);

                chart.timeScale().fitContent();

                window.gnTvChart = chart;
            })
            .catch(err => {
                container.innerHTML = '<div style="color:#ff4757;text-align:center;padding:40px;font-family:Inter,sans-serif">Error: ' + err.message + '</div>';
            });
    }
    """,
    Output("tradingview-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# CHART.JS TAB (TAB 7)
# =============================================================================

app.clientside_callback(
    """
    function(n_intervals) {
        const containerId = 'chartjs-container';
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!window.gnChartjsReady) {
            window.gnChartjsReady = true;

            // Load Chart.js
            if (!window.Chart) {
                const script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
                script.onload = () => initChartJs(container);
                document.head.appendChild(script);
            } else {
                initChartJs(container);
            }
        }
        return null;
    }

    function initChartJs(container) {
        container.innerHTML = '';

        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'width:100%;height:100%;display:flex;flex-wrap:wrap;padding:20px;box-sizing:border-box;gap:20px;';
        container.appendChild(wrapper);

        fetch('/api/graph-data')
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div style="color:#888;text-align:center;padding:40px;font-family:Inter,sans-serif">No articles yet. Run collector.py to fetch news.</div>';
                    return;
                }

                // Count by sentiment
                const sentimentCount = { positive: 0, negative: 0, neutral: 0 };
                // Count by source
                const sourceCount = {};
                // Count by asset class
                const assetCount = {};

                data.nodes.forEach(n => {
                    sentimentCount[n.sentiment]++;
                    sourceCount[n.source] = (sourceCount[n.source] || 0) + 1;
                    assetCount[n.asset_class] = (assetCount[n.asset_class] || 0) + 1;
                });

                // Donut Chart - Sentiment
                const donutDiv = document.createElement('div');
                donutDiv.style.cssText = 'flex:1;min-width:300px;height:300px;background:#1a1f2e;border-radius:8px;padding:16px;';
                donutDiv.innerHTML = '<canvas id="chartjs-sentiment"></canvas>';
                wrapper.appendChild(donutDiv);

                // Bar Chart - Sources
                const barDiv = document.createElement('div');
                barDiv.style.cssText = 'flex:1;min-width:300px;height:300px;background:#1a1f2e;border-radius:8px;padding:16px;';
                barDiv.innerHTML = '<canvas id="chartjs-sources"></canvas>';
                wrapper.appendChild(barDiv);

                // Pie Chart - Asset Classes
                const pieDiv = document.createElement('div');
                pieDiv.style.cssText = 'flex:1;min-width:300px;height:300px;background:#1a1f2e;border-radius:8px;padding:16px;';
                pieDiv.innerHTML = '<canvas id="chartjs-assets"></canvas>';
                wrapper.appendChild(pieDiv);

                // Sentiment Donut
                new Chart(document.getElementById('chartjs-sentiment'), {
                    type: 'doughnut',
                    data: {
                        labels: ['Positive', 'Negative', 'Neutral'],
                        datasets: [{
                            data: [sentimentCount.positive, sentimentCount.negative, sentimentCount.neutral],
                            backgroundColor: ['#00ff88', '#ff4757', '#888'],
                            borderColor: '#0a0e17',
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom', labels: { color: '#e0e0e0', font: { family: 'Inter' } } },
                            title: { display: true, text: 'Sentiment Distribution', color: '#ffd700', font: { family: 'Inter', size: 14 } }
                        }
                    }
                });

                // Sources Bar
                const sourceLabels = Object.keys(sourceCount).slice(0, 8);
                const sourceData = sourceLabels.map(l => sourceCount[l]);
                new Chart(document.getElementById('chartjs-sources'), {
                    type: 'bar',
                    data: {
                        labels: sourceLabels,
                        datasets: [{
                            label: 'Articles',
                            data: sourceData,
                            backgroundColor: 'rgba(255,215,0,0.6)',
                            borderColor: '#ffd700',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: true, text: 'Top Sources', color: '#ffd700', font: { family: 'Inter', size: 14 } }
                        },
                        scales: {
                            x: { ticks: { color: '#888', font: { family: 'Inter', size: 10 } }, grid: { color: '#ffffff11' } },
                            y: { ticks: { color: '#888', font: { family: 'Inter' } }, grid: { color: '#ffffff11' } }
                        }
                    }
                });

                // Asset Classes Pie
                const assetLabels = Object.keys(assetCount);
                const assetData = assetLabels.map(l => assetCount[l]);
                const assetColors = ['#ff6b35', '#ffd700', '#00d4ff', '#ff9500', '#00ff88', '#bf5af2', '#ff2d55', '#888'];
                new Chart(document.getElementById('chartjs-assets'), {
                    type: 'pie',
                    data: {
                        labels: assetLabels,
                        datasets: [{
                            data: assetData,
                            backgroundColor: assetColors.slice(0, assetLabels.length),
                            borderColor: '#0a0e17',
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom', labels: { color: '#e0e0e0', font: { family: 'Inter' } } },
                            title: { display: true, text: 'Asset Classes', color: '#ffd700', font: { family: 'Inter', size: 14 } }
                        }
                    }
                });
            })
            .catch(err => {
                container.innerHTML = '<div style="color:#ff4757;text-align:center;padding:40px;font-family:Inter,sans-serif">Error: ' + err.message + '</div>';
            });
    }
    """,
    Output("chartjs-container", "children"),
    Input("refresh-interval", "n_intervals")
)


# =============================================================================
# PURE HTML/CSS SIGNAL FEED TAB (TAB 8)
# =============================================================================

@callback(
    Output("signal-feed-container", "children"),
    Input("refresh-interval", "n_intervals")
)
def render_signal_feed(n_intervals):
    """Render pure HTML/CSS signal feed"""
    signals = get_active_signals(limit=30)
    articles = get_latest_articles(limit=20)

    if not signals:
        return html.Div([
            html.Div("⚡ Trading Signal Feed", style={"color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600", "marginBottom": "16px"}),
            html.Div("No signals yet. Run ai_analyzer.py to generate signals.", 
                    style={"color": COLORS["neutral"], "fontSize": "13px", "padding": "20px", 
                           "background": COLORS["card_bg"], "borderRadius": "8px", "textAlign": "center"})
        ])

    feed_items = []
    for sig in signals:
        direction_color = COLORS["positive"] if sig["direction"] == "long" else \
                         COLORS["negative"] if sig["direction"] == "short" else COLORS["neutral"]
        direction_arrow = "↑" if sig["direction"] == "long" else "↓" if sig["direction"] == "short" else "→"
        confidence_pct = int(sig["confidence"] * 100)
        asset_color = ASSET_COLORS.get(sig["asset_class"], COLORS["neutral"])

        feed_items.append(html.A(
            html.Div([
                # Header row
                html.Div([
                    html.Span(f"{direction_arrow} {sig['direction'].upper()}", style={
                        "color": direction_color, "fontWeight": "700", "fontSize": "14px"
                    }),
                    html.Span(f" {sig['asset_class'].upper()}", style={
                        "color": asset_color, "fontWeight": "600", "fontSize": "12px"
                    }),
                    html.Span(f" {confidence_pct}%", style={
                        "color": COLORS["neutral"], "fontSize": "12px"
                    }),
                    html.Span("CONFIRMED" if sig.get("is_active") else "PENDING", style={
                        "color": COLORS["positive"] if sig.get("is_active") else COLORS["neutral"],
                        "fontSize": "9px", "fontWeight": "600", "background": f"{COLORS['positive']}22" if sig.get("is_active") else f"{COLORS['neutral']}22",
                        "padding": "2px 6px", "borderRadius": "3px", "marginLeft": "auto"
                    }),
                ], style={"display": "flex", "alignItems": "center", "gap": "8px", "marginBottom": "8px"}),
                
                # Headline
                html.Div(sig.get("headline", "No headline"), style={
                    "color": COLORS["text"], "fontSize": "13px", "lineHeight": "1.4", "marginBottom": "8px"
                }),
                
                # Meta row
                html.Div([
                    html.Span(f"📰 {sig.get('source_name', 'Unknown')}", style={"color": COLORS["primary"], "fontSize": "10px"}),
                    html.Span(f" ⏱ {sig.get('time_horizon', 'N/A')}", style={"color": COLORS["neutral"], "fontSize": "10px"}),
                    html.Span(f" 📅 {sig.get('generated_at', '')[:10] if sig.get('generated_at') else 'N/A'}", style={"color": COLORS["neutral"], "fontSize": "10px"}),
                ], style={"display": "flex", "gap": "12px"}),
                
                # Confidence bar
                html.Div([
                    html.Div(style={
                        "width": f"{confidence_pct}%",
                        "height": "3px",
                        "background": direction_color,
                        "borderRadius": "2px",
                        "transition": "width 0.3s ease"
                    }),
                ], style={
                    "background": f"{COLORS['neutral']}22",
                    "borderRadius": "2px",
                    "marginTop": "8px",
                    "overflow": "hidden"
                }),
            ], style={
                "background": COLORS["card_bg"],
                "borderRadius": "8px",
                "padding": "16px",
                "marginBottom": "12px",
                "borderLeft": f"4px solid {direction_color}",
                "boxShadow": "0 2px 8px rgba(0,0,0,0.2)",
            }),
            href=sig.get("article_url") or f"https://www.google.com/search?q={sig.get('headline', '')}",
            target="_blank",
            style={"textDecoration": "none"}
        ))

    # Add separator
    feed_items.insert(0, html.Div("⚡ Trading Signal Feed", style={
        "color": COLORS["primary"], "fontSize": "16px", "fontWeight": "600", "marginBottom": "16px"
    }))

    return html.Div(feed_items, style={"maxWidth": "800px", "margin": "0 auto"})


# =============================================================================
# SIDEBAR UPDATE CALLBACK (preserved original functionality)
# =============================================================================

@callback(
    Output("last-update", "children"),
    Input("refresh-interval", "n_intervals")
)
def update_timestamp(n):
    from datetime import datetime
    return f"Updated: {datetime.now().strftime('%H:%M:%S')}"


# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == "__main__":
    print("🌐 Starting Golden News Dashboard...")
    print("📊 Dashboard: http://localhost:8050")
    print("📡 WebSocket: ws://localhost:8765")
    print("📋 8 Tabs: D3 Force | Cytoscape | Vis.js | Sigma | ECharts | TradingView | Chart.js | Signals")
    app.run(debug=False, host="0.0.0.0", port=8050)

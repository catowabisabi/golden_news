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

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "golden_news.db"

app = dash.Dash(__name__, title="Golden News Dashboard")
app.css.config.links.append({
    "rel": "stylesheet",
    "href": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
})

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
    cols = [desc[0] for desc in db.execute("SELECT * FROM news_articles LIMIT 1").description]
    cols.extend(["source_name", "category"])
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

            if len(shared) >= 2:
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

# Build the app layout
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("🏆 Golden News", style={
            "color": COLORS["primary"],
            "fontSize": "28px",
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
        "padding": "20px 30px",
        "background": COLORS["card_bg"],
        "borderBottom": f"1px solid {COLORS['primary']}22"
    }),

    # Main content
    html.Div([
        # Left: News Graph
        html.Div([
            html.H3("📊 News Relationship Graph", style={
                "color": COLORS["text"],
                "fontSize": "16px",
                "fontWeight": "600",
                "padding": "15px 20px 10px",
                "margin": "0"
            }),
            html.Div(id="graph-container", style={
                "height": "500px",
                "background": COLORS["background"],
                "borderRadius": "8px",
                "margin": "0 20px 20px",
                "overflow": "hidden"
            }),
        ], style={
            "flex": "1.5",
            "background": COLORS["card_bg"],
            "borderRadius": "12px",
            "margin": "20px",
        }),

        # Right: Signals + Articles
        html.Div([
            # Trading Signals
            html.H3("⚡ Active Trading Signals", style={
                "color": COLORS["primary"],
                "fontSize": "16px",
                "fontWeight": "600",
                "padding": "15px 20px 10px",
                "margin": "0"
            }),
            html.Div(id="signals-container", style={
                "maxHeight": "280px",
                "overflowY": "auto",
                "padding": "0 20px"
            }),

            html.Hr(style={"borderColor": COLORS["primary"] + "22", "margin": "20px 0"}),

            # Latest Articles
            html.H3("📰 Latest Articles", style={
                "color": COLORS["text"],
                "fontSize": "16px",
                "fontWeight": "600",
                "padding": "0 20px 10px",
                "margin": "0"
            }),
            html.Div(id="articles-container", style={
                "maxHeight": "400px",
                "overflowY": "auto",
                "padding": "0 20px 20px"
            }),
        ], style={
            "flex": "1",
            "background": COLORS["card_bg"],
            "borderRadius": "12px",
            "margin": "20px 20px 20px 0",
            "maxWidth": "450px"
        }),
    ], style={
        "display": "flex",
        "padding": "20px",
        "background": COLORS["background"],
        "minHeight": "calc(100vh - 80px)"
    }),

    # Auto-refresh interval
    dcc.Interval(id="refresh-interval", interval=30000, n_intervals=0),

    # Hidden div for storing graph data
    dcc.Store(id="graph-data-store"),
], style={
    "fontFamily": "Inter, sans-serif",
    "background": COLORS["background"],
    "minHeight": "100vh",
    "margin": "0"
})

@callback(
    Output("graph-data-store", "data"),
    Input("refresh-interval", "n_intervals")
)
def update_graph_data(n):
    return get_graph_data()

@callback(
    Output("graph-container", "children"),
    Output("signals-container", "children"),
    Output("articles-container", "children"),
    Output("last-update", "children"),
    Input("graph-data-store", "data")
)
def update_dashboard(data):
    if not data:
        return html.Div("Loading..."), [], [], ""

    from datetime import datetime
    last_update = f"Updated: {datetime.now().strftime('%H:%M:%S')}"

    # News Graph (D3.js style using Plotly)
    nodes = data["nodes"]
    edges = data["edges"]

    if not nodes:
        graph = html.Div("No articles yet. Run collector.py to fetch news.",
                         style={"color": COLORS["neutral"], "textAlign": "center", "padding": "200px 0"})
    else:
        # Use Plotly's built-in network graph (simpler than D3 for this demo)
        # For production, use actual D3.js via Html Iframe
        edge_x, edge_y, edge_colors = [], [], []
        for edge in edges:
            src = next((n for n in nodes if n["id"] == edge["source"]), None)
            tgt = next((n for n in nodes if n["id"] == edge["target"]), None)
            if src and tgt:
                edge_x.extend([nodes.index(src) * 10, nodes.index(tgt) * 10, None])
                edge_y.extend([0, 0, None])

        # Simple scatter for nodes
        fig = go.Figure()

        # Add edges as lines
        for edge in edges[:30]:  # Limit edges
            src = next((n for n in nodes if n["id"] == edge["source"]), None)
            tgt = next((n for n in nodes if n["id"] == edge["target"]), None)
            if src and tgt:
                si = nodes.index(src)
                ti = nodes.index(tgt)
                fig.add_trace(go.Scatter(
                    x=[si*10, ti*10],
                    y=[0, 0],
                    mode='lines',
                    line=dict(width=edge["strength"] * 2, color=COLORS["primary"] + "44"),
                    hoverinfo='text',
                    hovertext=f"Shared: {', '.join(edge['shared_keywords'][:3])}",
                    showlegend=False
                ))

        # Add nodes
        for node in nodes:
            i = nodes.index(node)
            color = COLORS["negative"] if node["sentiment"] == "negative" else \
                    COLORS["positive"] if node["sentiment"] == "positive" else COLORS["neutral"]
            size = 20 if node["is_signal"] else 10

            fig.add_trace(go.Scatter(
                x=[i * 10],
                y=[0],
                mode='markers+text',
                marker=dict(size=size, color=color, line=dict(width=1, color=COLORS["card_bg"])),
                text=node["source"][:8],
                textposition="bottom center",
                textfont=dict(color=COLORS["text"], size=8),
                hovertemplate=f"<b>{node['full_title']}</b><br>Source: {node['source']}<br>Sentiment: {node['sentiment']}<extra></extra>",
                showlegend=False
            ))

        fig.update_layout(
            paper_bgcolor=COLORS["background"],
            plot_bgcolor=COLORS["background"],
            font=dict(color=COLORS["text"], family="Inter"),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            hovermode='closest',
            margin=dict(l=20, r=20, t=20, b=40),
            height=480,
        )

        graph = dcc.Graph(
            figure=fig,
            config={"displayModeBar": False, "responsive": True},
            style={"height": "480px"}
        )

    # Signals
    signals_html = []
    for sig in data["signals"][:8]:
        direction_color = COLORS["positive"] if sig["direction"] == "long" else \
                          COLORS["negative"] if sig["direction"] == "short" else COLORS["neutral"]
        confidence_pct = int(sig["confidence"] * 100)

        signals_html.append(html.Div([
            html.Div([
                html.Span(f"{sig['direction'].upper()}", style={
                    "color": direction_color,
                    "fontWeight": "700",
                    "fontSize": "11px"
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
                "fontSize": "12px",
                "marginTop": "4px",
                "lineHeight": "1.4"
            }),
            html.Div(f"{sig.get('source_name', '')} • {sig.get('time_horizon', '')}", style={
                "color": COLORS["neutral"],
                "fontSize": "10px",
                "marginTop": "4px"
            }),
        ], style={
            "background": COLORS["background"],
            "borderRadius": "8px",
            "padding": "12px",
            "marginBottom": "10px",
            "borderLeft": f"3px solid {direction_color}",
        }))

    if not signals_html:
        signals_html = [html.Div("No signals yet. Run ai_analyzer.py to generate signals.",
                                 style={"color": COLORS["neutral"], "fontSize": "12px", "padding": "20px 0"})]

    # Articles
    articles_html = []
    for art in data["nodes"][:15]:
        sentiment_color = COLORS["positive"] if art["sentiment"] == "positive" else \
                         COLORS["negative"] if art["sentiment"] == "negative" else COLORS["neutral"]

        articles_html.append(html.A(
            html.Div([
                html.Div(art["title"], style={
                    "color": COLORS["text"],
                    "fontSize": "12px",
                    "lineHeight": "1.4",
                    "marginBottom": "4px"
                }),
                html.Div([
                    html.Span(art["source"], style={"color": COLORS["primary"], "fontSize": "10px"}),
                    html.Span(f" • {art['sentiment']}", style={"color": sentiment_color, "fontSize": "10px"}),
                ], style={"display": "flex", "gap": "8px"}),
            ], style={"padding": "10px 0", "borderBottom": f"1px solid {COLORS['primary']}11"}),
            href=art["url"] if art["url"] else "#",
            target="_blank",
            style={"textDecoration": "none"}
        ))

    return graph, signals_html, articles_html, last_update

if __name__ == "__main__":
    print("🌐 Starting Golden News Dashboard...")
    print("📊 Dashboard: http://localhost:8050")
    print("📡 WebSocket: ws://localhost:8765")
    app.run(debug=False, host="0.0.0.0", port=8050)

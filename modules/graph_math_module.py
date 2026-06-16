import heapq
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Set, Tuple

from PIL import Image, ImageDraw, ImageFont
from telegram import InputFile, Update
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    from utils import split_long_text
except Exception:
    def split_long_text(text: str, limit: int = 3500) -> List[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        current = ""
        for line in text.splitlines():
            if len(current) + len(line) + 1 > limit:
                if current:
                    chunks.append(current)
                current = line
            else:
                current += ("\n" if current else "") + line
        if current:
            chunks.append(current)
        return chunks


# ------------------------------------------------------------
# Strict limits for Render Free safety
# ------------------------------------------------------------

MAX_GRAPH_NODES = 50
MAX_GRAPH_EDGES = 200
MAX_CONVEX_HULL_POINTS = 500
MAX_LABEL_LENGTH = 32


# ------------------------------------------------------------
# Data models
# ------------------------------------------------------------

@dataclass(frozen=True)
class Edge:
    u: str
    v: str
    weight: float = 1.0


Point = Tuple[float, float]


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def graph_help_text() -> str:
    return (
        "Graph theory commands:\n\n"
        "Geometry:\n"
        "/convexhull 0,0 1,2 2,1 0,3 3,0 - draw convex hull\n\n"
        "Graph drawing:\n"
        "/graphdraw A B; A C; B D; C D - draw an undirected graph\n"
        "/graphdraw directed | A B; A C; B D - draw a directed graph\n\n"
        "Shortest paths:\n"
        "/dijkstra A D | A B 4; A C 2; C B 1; B D 5; C D 8\n"
        "/dijkstra directed A D | A B 4; B C 2; A C 10\n"
        "/shortestpath A E | A B; A C; B D; C D; D E\n\n"
        "Trees and traversal:\n"
        "/mst A B 4; A C 2; C B 1; B D 5; C D 8\n"
        "/bfs A | A B; A C; B D; C E\n"
        "/dfs A | A B; A C; B D; C E\n\n"
        "Graph properties:\n"
        "/components A B; B C; D E\n"
        "/toposort shop cook; cook eat; study exam\n"
        "/bipartite A 1; A 2; B 1; B 2\n"
        "/cycle A B; B C; C A\n"
        "/cycle directed | A B; B C; C A\n\n"
        "Limits:\n"
        f"- Maximum graph nodes: {MAX_GRAPH_NODES}\n"
        f"- Maximum graph edges: {MAX_GRAPH_EDGES}\n"
        f"- Maximum convex hull points: {MAX_CONVEX_HULL_POINTS}\n\n"
        "Notes:\n"
        "- Use semicolon ; between edges\n"
        "- Edge format: node1 node2 or node1 node2 weight\n"
        "- Node labels cannot contain spaces\n"
        "- Dijkstra weights must be non-negative"
    )


def clean_label(label: str) -> str:
    label = label.strip()
    label = label.strip(",;()[]{}")

    if not label:
        raise ValueError("Empty node label found.")

    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"Node label is too long: {label}")

    return label


def fmt_number(value: float) -> str:
    if abs(value) < 1e-10:
        value = 0.0

    if abs(value - round(value)) < 1e-10:
        return str(int(round(value)))

    return f"{value:.6g}"


def sendable_path(path: List[str]) -> str:
    return " → ".join(path)


def normalize_undirected_edge(u: str, v: str) -> Tuple[str, str]:
    return tuple(sorted((u, v)))


def directed_edge_key(u: str, v: str) -> Tuple[str, str]:
    return (u, v)


# ------------------------------------------------------------
# Parsing graph inputs
# ------------------------------------------------------------

def args_to_text(args: List[str]) -> str:
    return " ".join(args).strip()


def parse_directed_prefix(text: str) -> Tuple[bool, str]:
    text = text.strip()

    if text.lower().startswith("directed |"):
        return True, text.split("|", 1)[1].strip()

    if text.lower().startswith("directed "):
        return True, text[len("directed "):].strip()

    return False, text


def split_header_and_edges(text: str) -> Tuple[str, str]:
    if "|" not in text:
        raise ValueError("Missing | separator. Example: /bfs A | A B; A C")

    header, edges_text = text.split("|", 1)
    return header.strip(), edges_text.strip()


def parse_edges(edges_text: str, weighted: bool = False, allow_unweighted_in_weighted: bool = False) -> List[Edge]:
    edges_text = edges_text.strip()

    if not edges_text:
        raise ValueError("Please provide at least one edge.")

    raw_edges = [part.strip() for part in edges_text.split(";") if part.strip()]

    if len(raw_edges) > MAX_GRAPH_EDGES:
        raise ValueError(f"Too many edges. Maximum allowed is {MAX_GRAPH_EDGES}.")

    edges: List[Edge] = []

    for raw_edge in raw_edges:
        parts = raw_edge.replace(",", " ").split()

        if weighted:
            if len(parts) == 2 and allow_unweighted_in_weighted:
                u = clean_label(parts[0])
                v = clean_label(parts[1])
                weight = 1.0
            elif len(parts) == 3:
                u = clean_label(parts[0])
                v = clean_label(parts[1])
                try:
                    weight = float(parts[2])
                except Exception:
                    raise ValueError(f"Invalid edge weight in: {raw_edge}")
            else:
                raise ValueError(f"Invalid weighted edge: {raw_edge}. Use: A B 4")
        else:
            if len(parts) < 2:
                raise ValueError(f"Invalid edge: {raw_edge}. Use: A B")
            u = clean_label(parts[0])
            v = clean_label(parts[1])
            weight = 1.0

        if u == v:
            raise ValueError(f"Self-loops are not supported here: {u} {v}")

        edges.append(Edge(u, v, weight))

    validate_graph_limits(edges)
    return edges


def validate_graph_limits(edges: List[Edge]) -> None:
    nodes = nodes_from_edges(edges)

    if len(nodes) > MAX_GRAPH_NODES:
        raise ValueError(f"Too many nodes. Maximum allowed is {MAX_GRAPH_NODES}.")

    if len(edges) > MAX_GRAPH_EDGES:
        raise ValueError(f"Too many edges. Maximum allowed is {MAX_GRAPH_EDGES}.")


def nodes_from_edges(edges: Iterable[Edge]) -> Set[str]:
    nodes: Set[str] = set()

    for edge in edges:
        nodes.add(edge.u)
        nodes.add(edge.v)

    return nodes


def parse_source_target_command(args: List[str], weighted: bool) -> Tuple[bool, str, str, List[Edge]]:
    text = args_to_text(args)

    if not text:
        raise ValueError("Missing command input.")

    directed, rest = parse_directed_prefix(text)
    header, edges_text = split_header_and_edges(rest)
    header_parts = header.split()

    if len(header_parts) != 2:
        raise ValueError("Please provide source and target before |. Example: A D | A B 4; B D 5")

    source = clean_label(header_parts[0])
    target = clean_label(header_parts[1])
    edges = parse_edges(edges_text, weighted=weighted, allow_unweighted_in_weighted=False)

    nodes = nodes_from_edges(edges)

    if source not in nodes:
        raise ValueError(f"Source node is not in the graph: {source}")

    if target not in nodes:
        raise ValueError(f"Target node is not in the graph: {target}")

    return directed, source, target, edges


def parse_start_command(args: List[str]) -> Tuple[bool, str, List[Edge]]:
    text = args_to_text(args)

    if not text:
        raise ValueError("Missing command input.")

    directed, rest = parse_directed_prefix(text)
    header, edges_text = split_header_and_edges(rest)
    header_parts = header.split()

    if len(header_parts) != 1:
        raise ValueError("Please provide one start node before |. Example: /bfs A | A B; A C")

    start = clean_label(header_parts[0])
    edges = parse_edges(edges_text, weighted=False)
    nodes = nodes_from_edges(edges)

    if start not in nodes:
        raise ValueError(f"Start node is not in the graph: {start}")

    return directed, start, edges


# ------------------------------------------------------------
# Graph algorithms
# ------------------------------------------------------------

def build_adjacency(edges: List[Edge], directed: bool = False, weighted: bool = False) -> Dict[str, List[Tuple[str, float]]]:
    adjacency: Dict[str, List[Tuple[str, float]]] = defaultdict(list)

    for edge in edges:
        weight = edge.weight if weighted else 1.0
        adjacency[edge.u].append((edge.v, weight))
        adjacency.setdefault(edge.v, [])

        if not directed:
            adjacency[edge.v].append((edge.u, weight))
            adjacency.setdefault(edge.u, [])

    for node in adjacency:
        adjacency[node].sort(key=lambda item: item[0])

    return adjacency


def dijkstra_shortest_path(edges: List[Edge], source: str, target: str, directed: bool = False) -> Tuple[float, List[str]]:
    for edge in edges:
        if edge.weight < 0:
            raise ValueError("Dijkstra requires non-negative weights.")

    adjacency = build_adjacency(edges, directed=directed, weighted=True)
    distances = {node: math.inf for node in adjacency}
    previous: Dict[str, Optional[str]] = {node: None for node in adjacency}

    distances[source] = 0.0
    heap: List[Tuple[float, str]] = [(0.0, source)]

    while heap:
        current_distance, node = heapq.heappop(heap)

        if current_distance != distances[node]:
            continue

        if node == target:
            break

        for neighbor, weight in adjacency[node]:
            candidate = current_distance + weight

            if candidate < distances[neighbor]:
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(heap, (candidate, neighbor))

    if math.isinf(distances[target]):
        return math.inf, []

    path = []
    node = target

    while node is not None:
        path.append(node)
        node = previous[node]

    path.reverse()
    return distances[target], path


def bfs_shortest_path(edges: List[Edge], source: str, target: str, directed: bool = False) -> List[str]:
    adjacency = build_adjacency(edges, directed=directed, weighted=False)
    queue = deque([source])
    previous: Dict[str, Optional[str]] = {source: None}

    while queue:
        node = queue.popleft()

        if node == target:
            break

        for neighbor, _ in adjacency[node]:
            if neighbor not in previous:
                previous[neighbor] = node
                queue.append(neighbor)

    if target not in previous:
        return []

    path = []
    node = target

    while node is not None:
        path.append(node)
        node = previous[node]

    path.reverse()
    return path


def traversal_order(edges: List[Edge], start: str, directed: bool, mode: str) -> List[str]:
    adjacency = build_adjacency(edges, directed=directed, weighted=False)
    visited: Set[str] = set()
    order: List[str] = []

    if mode == "bfs":
        queue = deque([start])
        visited.add(start)

        while queue:
            node = queue.popleft()
            order.append(node)

            for neighbor, _ in adjacency[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

    else:
        stack = [start]

        while stack:
            node = stack.pop()

            if node in visited:
                continue

            visited.add(node)
            order.append(node)

            neighbors = [neighbor for neighbor, _ in adjacency[node]]
            for neighbor in reversed(neighbors):
                if neighbor not in visited:
                    stack.append(neighbor)

    return order


def connected_components(edges: List[Edge]) -> List[List[str]]:
    adjacency = build_adjacency(edges, directed=False, weighted=False)
    visited: Set[str] = set()
    components: List[List[str]] = []

    for start in sorted(adjacency):
        if start in visited:
            continue

        component: List[str] = []
        queue = deque([start])
        visited.add(start)

        while queue:
            node = queue.popleft()
            component.append(node)

            for neighbor, _ in adjacency[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        components.append(sorted(component))

    components.sort(key=lambda comp: (len(comp), comp), reverse=True)
    return components


def kruskal_mst(edges: List[Edge]) -> Tuple[List[Edge], float]:
    nodes = sorted(nodes_from_edges(edges))
    parent = {node: node for node in nodes}
    rank = {node: 0 for node in nodes}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> bool:
        root_a = find(a)
        root_b = find(b)

        if root_a == root_b:
            return False

        if rank[root_a] < rank[root_b]:
            parent[root_a] = root_b
        elif rank[root_a] > rank[root_b]:
            parent[root_b] = root_a
        else:
            parent[root_b] = root_a
            rank[root_a] += 1

        return True

    mst_edges: List[Edge] = []
    total = 0.0

    for edge in sorted(edges, key=lambda edge: (edge.weight, edge.u, edge.v)):
        if union(edge.u, edge.v):
            mst_edges.append(edge)
            total += edge.weight

    if len(mst_edges) != max(0, len(nodes) - 1):
        raise ValueError("Graph is disconnected. MST does not exist for all nodes.")

    return mst_edges, total


def topological_sort(edges: List[Edge]) -> Tuple[List[str], bool]:
    nodes = sorted(nodes_from_edges(edges))
    adjacency: Dict[str, List[str]] = {node: [] for node in nodes}
    indegree: Dict[str, int] = {node: 0 for node in nodes}

    for edge in edges:
        adjacency[edge.u].append(edge.v)
        indegree[edge.v] += 1

    for node in adjacency:
        adjacency[node].sort()

    queue = deque(sorted(node for node in nodes if indegree[node] == 0))
    order: List[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)

        for neighbor in adjacency[node]:
            indegree[neighbor] -= 1

            if indegree[neighbor] == 0:
                queue.append(neighbor)

    has_cycle = len(order) != len(nodes)
    return order, has_cycle


def is_bipartite_graph(edges: List[Edge]) -> Tuple[bool, Dict[str, int], Optional[Tuple[str, str]]]:
    adjacency = build_adjacency(edges, directed=False, weighted=False)
    color: Dict[str, int] = {}

    for start in sorted(adjacency):
        if start in color:
            continue

        color[start] = 0
        queue = deque([start])

        while queue:
            node = queue.popleft()

            for neighbor, _ in adjacency[node]:
                if neighbor not in color:
                    color[neighbor] = 1 - color[node]
                    queue.append(neighbor)
                elif color[neighbor] == color[node]:
                    return False, color, (node, neighbor)

    return True, color, None


def has_undirected_cycle(edges: List[Edge]) -> Tuple[bool, Optional[List[str]]]:
    adjacency = build_adjacency(edges, directed=False, weighted=False)
    visited: Set[str] = set()
    parent: Dict[str, Optional[str]] = {}

    for start in sorted(adjacency):
        if start in visited:
            continue

        stack = [(start, None)]
        parent[start] = None

        while stack:
            node, prev = stack.pop()

            if node not in visited:
                visited.add(node)

            for neighbor, _ in adjacency[node]:
                if neighbor == prev:
                    continue

                if neighbor in visited:
                    return True, [node, neighbor]

                parent[neighbor] = node
                stack.append((neighbor, node))

    return False, None


def has_directed_cycle(edges: List[Edge]) -> Tuple[bool, Optional[List[str]]]:
    adjacency = build_adjacency(edges, directed=True, weighted=False)
    state: Dict[str, int] = {node: 0 for node in adjacency}  # 0 new, 1 visiting, 2 done
    parent: Dict[str, Optional[str]] = {}

    def dfs(node: str) -> Tuple[bool, Optional[List[str]]]:
        state[node] = 1

        for neighbor, _ in adjacency[node]:
            if state[neighbor] == 0:
                parent[neighbor] = node
                found, cycle = dfs(neighbor)
                if found:
                    return True, cycle
            elif state[neighbor] == 1:
                return True, [node, neighbor]

        state[node] = 2
        return False, None

    for node in sorted(adjacency):
        if state[node] == 0:
            parent[node] = None
            found, cycle = dfs(node)
            if found:
                return True, cycle

    return False, None


# ------------------------------------------------------------
# Convex hull
# ------------------------------------------------------------

def parse_points(args: List[str]) -> List[Point]:
    text = args_to_text(args)

    if not text:
        raise ValueError("Please provide points. Example: /convexhull 0,0 1,2 2,1")

    raw_points = [part.strip() for part in re.split(r"[;\s]+", text) if part.strip()]

    if len(raw_points) > MAX_CONVEX_HULL_POINTS:
        raise ValueError(f"Too many points. Maximum allowed is {MAX_CONVEX_HULL_POINTS}.")

    points: List[Point] = []

    for raw_point in raw_points:
        if "," not in raw_point:
            raise ValueError(f"Invalid point: {raw_point}. Use x,y")

        x_text, y_text = raw_point.split(",", 1)

        try:
            x = float(x_text)
            y = float(y_text)
        except Exception:
            raise ValueError(f"Invalid point: {raw_point}. Use numeric x,y")

        points.append((x, y))

    unique_points = sorted(set(points))

    if len(unique_points) < 3:
        raise ValueError("Convex hull needs at least 3 unique points.")

    return unique_points


def cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points: List[Point]) -> List[Point]:
    points = sorted(set(points))

    if len(points) <= 1:
        return points

    lower: List[Point] = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: List[Point] = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def polygon_area(points: List[Point]) -> float:
    if len(points) < 3:
        return 0.0

    total = 0.0
    n = len(points)

    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1

    return abs(total) / 2.0


# ------------------------------------------------------------
# Drawing helpers
# ------------------------------------------------------------

def load_font(size: int = 22):
    possible_fonts = [
        "arial.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for font_path in possible_fonts:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass

    return ImageFont.load_default()


def graph_layout(nodes: List[str], width: int, height: int, margin: int = 120) -> Dict[str, Tuple[int, int]]:
    nodes = sorted(nodes)
    n = len(nodes)

    if n == 1:
        return {nodes[0]: (width // 2, height // 2)}

    center_x = width // 2
    center_y = height // 2 + 20
    radius = min(width, height) // 2 - margin

    positions = {}

    for index, node in enumerate(nodes):
        angle = -math.pi / 2 + 2 * math.pi * index / n
        x = int(center_x + radius * math.cos(angle))
        y = int(center_y + radius * math.sin(angle))
        positions[node] = (x, y)

    return positions


def draw_arrowhead(draw: ImageDraw.ImageDraw, start: Tuple[int, int], end: Tuple[int, int], fill: str, size: int = 14) -> None:
    x1, y1 = start
    x2, y2 = end
    angle = math.atan2(y2 - y1, x2 - x1)

    left = (
        x2 - size * math.cos(angle - math.pi / 6),
        y2 - size * math.sin(angle - math.pi / 6),
    )
    right = (
        x2 - size * math.cos(angle + math.pi / 6),
        y2 - size * math.sin(angle + math.pi / 6),
    )

    draw.polygon([end, left, right], fill=fill)


def edge_highlight_keys_from_path(path: List[str], directed: bool) -> Set[Tuple[str, str]]:
    keys: Set[Tuple[str, str]] = set()

    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        keys.add(directed_edge_key(u, v) if directed else normalize_undirected_edge(u, v))

    return keys


def edge_highlight_keys(edges: List[Edge], directed: bool) -> Set[Tuple[str, str]]:
    keys: Set[Tuple[str, str]] = set()

    for edge in edges:
        keys.add(directed_edge_key(edge.u, edge.v) if directed else normalize_undirected_edge(edge.u, edge.v))

    return keys


def create_graph_image(
    edges: List[Edge],
    title: str,
    directed: bool = False,
    weighted: bool = False,
    highlight: Optional[Set[Tuple[str, str]]] = None,
    caption_lines: Optional[List[str]] = None,
) -> BytesIO:
    width = 1200
    height = 900
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(34)
    label_font = load_font(22)
    small_font = load_font(18)

    nodes = sorted(nodes_from_edges(edges))
    positions = graph_layout(nodes, width, height)
    highlight = highlight or set()

    draw.text((50, 30), title, fill="black", font=title_font)

    if caption_lines:
        y = 75
        for line in caption_lines[:4]:
            draw.text((50, y), line, fill="#444444", font=small_font)
            y += 24

    # Draw edges.
    for edge in edges:
        x1, y1 = positions[edge.u]
        x2, y2 = positions[edge.v]
        key = directed_edge_key(edge.u, edge.v) if directed else normalize_undirected_edge(edge.u, edge.v)
        is_highlighted = key in highlight

        line_color = "#d62728" if is_highlighted else "#777777"
        line_width = 6 if is_highlighted else 3

        # Shorten line near node circles.
        dx = x2 - x1
        dy = y2 - y1
        distance = math.hypot(dx, dy) or 1
        shrink = 34
        sx = int(x1 + dx / distance * shrink)
        sy = int(y1 + dy / distance * shrink)
        ex = int(x2 - dx / distance * shrink)
        ey = int(y2 - dy / distance * shrink)

        draw.line((sx, sy, ex, ey), fill=line_color, width=line_width)

        if directed:
            draw_arrowhead(draw, (sx, sy), (ex, ey), fill=line_color)

        if weighted:
            mx = (sx + ex) // 2
            my = (sy + ey) // 2
            label = fmt_number(edge.weight)
            bbox = draw.textbbox((0, 0), label, font=small_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.rounded_rectangle((mx - tw // 2 - 8, my - th // 2 - 6, mx + tw // 2 + 8, my + th // 2 + 6), radius=8, fill="white", outline="#aaaaaa")
            draw.text((mx - tw // 2, my - th // 2 - 2), label, fill="black", font=small_font)

    # Draw nodes.
    for node in nodes:
        x, y = positions[node]
        radius = 31
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="#4f8cff", outline="#1f3f75", width=3)

        label = node if len(node) <= 8 else node[:7] + "…"
        bbox = draw.textbbox((0, 0), label, font=label_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((x - tw // 2, y - th // 2 - 2), label, fill="white", font=label_font)

    draw.text((50, height - 45), f"Nodes: {len(nodes)} | Edges: {len(edges)} | LakLak graph math", fill="#555555", font=small_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "graph.png"
    return output


def create_convex_hull_image(points: List[Point], hull: List[Point]) -> BytesIO:
    width = 1200
    height = 900
    margin = 90

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = load_font(34)
    label_font = load_font(20)
    small_font = load_font(18)

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    if abs(xmax - xmin) < 1e-12:
        xmin -= 1
        xmax += 1

    if abs(ymax - ymin) < 1e-12:
        ymin -= 1
        ymax += 1

    xpad = (xmax - xmin) * 0.10
    ypad = (ymax - ymin) * 0.10
    xmin -= xpad
    xmax += xpad
    ymin -= ypad
    ymax += ypad

    def map_point(point: Point) -> Tuple[int, int]:
        x, y = point
        px = int(margin + (x - xmin) / (xmax - xmin) * (width - 2 * margin))
        py = int(height - margin - (y - ymin) / (ymax - ymin) * (height - 2 * margin))
        return px, py

    draw.text((50, 30), "Convex hull", fill="black", font=title_font)
    draw.text((50, 75), f"Points: {len(points)} | Hull vertices: {len(hull)} | Area: {fmt_number(polygon_area(hull))}", fill="#444444", font=small_font)

    # Grid.
    for i in range(11):
        x = margin + i * (width - 2 * margin) / 10
        y = margin + i * (height - 2 * margin) / 10
        draw.line((x, margin, x, height - margin), fill="#eeeeee", width=1)
        draw.line((margin, y, width - margin, y), fill="#eeeeee", width=1)

    # Hull polygon.
    hull_pixels = [map_point(point) for point in hull]
    if len(hull_pixels) >= 3:
        draw.polygon(hull_pixels, fill="#dff0ff", outline="#d62728")
        draw.line(hull_pixels + [hull_pixels[0]], fill="#d62728", width=5)

    # Points.
    hull_set = set(hull)
    for point in points:
        px, py = map_point(point)
        if point in hull_set:
            draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill="#d62728")
        else:
            draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill="#1f77b4")

    # Label hull points only, to avoid clutter.
    for point in hull:
        px, py = map_point(point)
        label = f"({fmt_number(point[0])},{fmt_number(point[1])})"
        draw.text((px + 10, py - 10), label, fill="#333333", font=label_font)

    draw.text((50, height - 45), "Convex hull computed with monotonic chain algorithm", fill="#555555", font=small_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "convex_hull.png"
    return output


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

async def graphhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(graph_help_text())


async def convexhull_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        points = parse_points(context.args)
        hull = convex_hull(points)
        image = create_convex_hull_image(points, hull)

        hull_text = " → ".join(f"({fmt_number(x)},{fmt_number(y)})" for x, y in hull)
        caption = (
            "Convex hull\n"
            f"Hull vertices: {len(hull)}\n"
            f"Area: {fmt_number(polygon_area(hull))}\n"
            f"Hull: {hull_text}"
        )

        await update.message.reply_photo(photo=InputFile(image, filename="convex_hull.png"), caption=caption[:1024])

    except Exception as error:
        await update.message.reply_text(
            "Convex hull error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/convexhull 0,0 1,2 2,1 0,3 3,0 2,4"
        )


async def graphdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        text = args_to_text(context.args)
        directed, rest = parse_directed_prefix(text)

        # Allow /graphdraw directed | A B; B C
        if rest.startswith("|"):
            rest = rest[1:].strip()

        edges = parse_edges(rest, weighted=True, allow_unweighted_in_weighted=True)
        weighted = any(abs(edge.weight - 1.0) > 1e-12 for edge in edges)
        image = create_graph_image(edges, title="Graph drawing", directed=directed, weighted=weighted)

        caption = f"Graph drawing | Nodes: {len(nodes_from_edges(edges))} | Edges: {len(edges)}"
        await update.message.reply_photo(photo=InputFile(image, filename="graph.png"), caption=caption)

    except Exception as error:
        await update.message.reply_text(
            "Graph draw error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/graphdraw A B; A C; B D; C D\n"
            "/graphdraw directed | A B; A C; B D"
        )


async def dijkstra_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        directed, source, target, edges = parse_source_target_command(context.args, weighted=True)
        distance, path = dijkstra_shortest_path(edges, source, target, directed=directed)

        if not path:
            await update.message.reply_text(f"No path found from {source} to {target}.")
            return

        highlight = edge_highlight_keys_from_path(path, directed=directed)
        image = create_graph_image(
            edges,
            title="Dijkstra shortest path",
            directed=directed,
            weighted=True,
            highlight=highlight,
            caption_lines=[f"Path: {sendable_path(path)}", f"Total distance: {fmt_number(distance)}"],
        )

        text = (
            "Dijkstra shortest path\n\n"
            f"From: {source}\n"
            f"To: {target}\n"
            f"Path: {sendable_path(path)}\n"
            f"Total distance: {fmt_number(distance)}"
        )

        await update.message.reply_photo(photo=InputFile(image, filename="dijkstra.png"), caption=text[:1024])

    except Exception as error:
        await update.message.reply_text(
            "Dijkstra error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/dijkstra A D | A B 4; A C 2; C B 1; B D 5; C D 8\n"
            "/dijkstra directed A D | A B 4; B D 3"
        )


async def shortestpath_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        directed, source, target, edges = parse_source_target_command(context.args, weighted=False)
        path = bfs_shortest_path(edges, source, target, directed=directed)

        if not path:
            await update.message.reply_text(f"No path found from {source} to {target}.")
            return

        highlight = edge_highlight_keys_from_path(path, directed=directed)
        image = create_graph_image(
            edges,
            title="Unweighted shortest path",
            directed=directed,
            weighted=False,
            highlight=highlight,
            caption_lines=[f"Path: {sendable_path(path)}", f"Length: {len(path) - 1} edges"],
        )

        text = (
            "Unweighted shortest path\n\n"
            f"From: {source}\n"
            f"To: {target}\n"
            f"Path: {sendable_path(path)}\n"
            f"Length: {len(path) - 1} edges"
        )

        await update.message.reply_photo(photo=InputFile(image, filename="shortest_path.png"), caption=text[:1024])

    except Exception as error:
        await update.message.reply_text(
            "Shortest path error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/shortestpath A E | A B; A C; B D; C D; D E"
        )


async def mst_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        edges = parse_edges(args_to_text(context.args), weighted=True)
        mst_edges, total = kruskal_mst(edges)
        highlight = edge_highlight_keys(mst_edges, directed=False)
        image = create_graph_image(
            edges,
            title="Minimum spanning tree",
            directed=False,
            weighted=True,
            highlight=highlight,
            caption_lines=[f"Total weight: {fmt_number(total)}", f"MST edges: {len(mst_edges)}"],
        )

        lines = ["Minimum spanning tree", "", "Edges:"]
        for edge in mst_edges:
            lines.append(f"{edge.u} - {edge.v}: {fmt_number(edge.weight)}")
        lines.extend(["", f"Total weight: {fmt_number(total)}"])

        await update.message.reply_photo(photo=InputFile(image, filename="mst.png"), caption="\n".join(lines)[:1024])

    except Exception as error:
        await update.message.reply_text(
            "MST error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/mst A B 4; A C 2; C B 1; B D 5; C D 8"
        )


async def bfs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        directed, start, edges = parse_start_command(context.args)
        order = traversal_order(edges, start, directed=directed, mode="bfs")
        await update.message.reply_text("BFS traversal\n\n" f"Start: {start}\n" f"Order: {sendable_path(order)}")

    except Exception as error:
        await update.message.reply_text(
            "BFS error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/bfs A | A B; A C; B D; C E"
        )


async def dfs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        directed, start, edges = parse_start_command(context.args)
        order = traversal_order(edges, start, directed=directed, mode="dfs")
        await update.message.reply_text("DFS traversal\n\n" f"Start: {start}\n" f"Order: {sendable_path(order)}")

    except Exception as error:
        await update.message.reply_text(
            "DFS error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/dfs A | A B; A C; B D; C E"
        )


async def components_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        edges = parse_edges(args_to_text(context.args), weighted=False)
        comps = connected_components(edges)

        lines = ["Connected components", "", f"Count: {len(comps)}", ""]
        for index, comp in enumerate(comps, start=1):
            lines.append(f"Component {index}: {', '.join(comp)}")

        for chunk in split_long_text("\n".join(lines)):
            await update.message.reply_text(chunk)

    except Exception as error:
        await update.message.reply_text(
            "Components error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/components A B; B C; D E"
        )


async def toposort_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        edges = parse_edges(args_to_text(context.args), weighted=False)
        order, has_cycle = topological_sort(edges)

        if has_cycle:
            await update.message.reply_text(
                "Topological sort failed.\n\n"
                "The directed graph has a cycle, so no topological ordering exists."
            )
            return

        await update.message.reply_text("Topological order\n\n" + sendable_path(order))

    except Exception as error:
        await update.message.reply_text(
            "Toposort error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/toposort shop cook; cook eat; study exam"
        )


async def bipartite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        edges = parse_edges(args_to_text(context.args), weighted=False)
        ok, color, conflict = is_bipartite_graph(edges)

        if ok:
            left = sorted(node for node, value in color.items() if value == 0)
            right = sorted(node for node, value in color.items() if value == 1)
            text = (
                "Bipartite check\n\n"
                "Result: yes ✅\n\n"
                f"Set 1: {', '.join(left)}\n"
                f"Set 2: {', '.join(right)}"
            )
        else:
            if conflict:
                text = (
                    "Bipartite check\n\n"
                    "Result: no ❌\n"
                    f"Conflict edge: {conflict[0]} - {conflict[1]}"
                )
            else:
                text = "Bipartite check\n\nResult: no ❌"

        await update.message.reply_text(text)

    except Exception as error:
        await update.message.reply_text(
            "Bipartite error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/bipartite A 1; A 2; B 1; B 2"
        )


async def cycle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        text = args_to_text(context.args)
        directed, rest = parse_directed_prefix(text)

        if rest.startswith("|"):
            rest = rest[1:].strip()

        edges = parse_edges(rest, weighted=False)

        if directed:
            found, witness = has_directed_cycle(edges)
        else:
            found, witness = has_undirected_cycle(edges)

        if found:
            detail = f"\nWitness edge: {witness[0]} → {witness[1]}" if witness and directed else ""
            if witness and not directed:
                detail = f"\nWitness edge: {witness[0]} - {witness[1]}"
            await update.message.reply_text(f"Cycle check\n\nResult: cycle found ✅{detail}")
        else:
            await update.message.reply_text("Cycle check\n\nResult: no cycle found ❌")

    except Exception as error:
        await update.message.reply_text(
            "Cycle check error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/cycle A B; B C; C A\n"
            "/cycle directed | A B; B C; C A"
        )


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

def register_graph_math_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("convexhull", convexhull_command))
    app.add_handler(CommandHandler("graphdraw", graphdraw_command))
    app.add_handler(CommandHandler("dijkstra", dijkstra_command))
    app.add_handler(CommandHandler("shortestpath", shortestpath_command))
    app.add_handler(CommandHandler("mst", mst_command))
    app.add_handler(CommandHandler("bfs", bfs_command))
    app.add_handler(CommandHandler("dfs", dfs_command))
    app.add_handler(CommandHandler("components", components_command))
    app.add_handler(CommandHandler("toposort", toposort_command))
    app.add_handler(CommandHandler("bipartite", bipartite_command))
    app.add_handler(CommandHandler("cycle", cycle_command))
    app.add_handler(CommandHandler("graphhelp", graphhelp_command))

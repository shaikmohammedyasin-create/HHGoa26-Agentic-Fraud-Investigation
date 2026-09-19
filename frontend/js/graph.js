/**
 * Interactive Knowledge Graph Renderer using HTML5 Canvas
 * Renders case-scoped entities and relationships with physics layout.
 */
class GraphRenderer {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.nodes = [];
    this.links = [];
    this.selectedNode = null;
    this.hoveredNode = null;

    // Viewport transform
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.isDragging = false;
    this.dragNode = null;
    this.lastMouse = { x: 0, y: 0 };

    this.initEvents();
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    if (!this.canvas || !this.canvas.parentElement) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = this.width * window.devicePixelRatio;
    this.canvas.height = this.height * window.devicePixelRatio;
    this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    this.render();
  }

  setData(graphData) {
    if (!graphData || !graphData.nodes) {
      this.nodes = [];
      this.links = [];
      this.render();
      return;
    }

    const cx = this.width / 2;
    const cy = this.height / 2;

    // Build nodes with initial radial positions around center
    this.nodes = graphData.nodes.map((n, i) => {
      const angle = (i / graphData.nodes.length) * Math.PI * 2;
      const radius = n.type === 'FlaggedTransaction' ? 0 : 120 + (i % 3) * 60;
      return {
        ...n,
        x: cx + Math.cos(angle) * radius + (Math.random() - 0.5) * 20,
        y: cy + Math.sin(angle) * radius + (Math.random() - 0.5) * 20,
        vx: 0,
        vy: 0,
        radius: this.getNodeRadius(n.type),
        color: this.getNodeColor(n.type)
      };
    });

    const nodeMap = new Map(this.nodes.map(n => [n.id, n]));
    this.links = (graphData.links || [])
      .map(l => ({
        source: nodeMap.get(l.source),
        target: nodeMap.get(l.target),
        type: l.type
      }))
      .filter(l => l.source && l.target);

    // Run short physics simulation
    this.simulate(60);
    this.render();
  }

  getNodeRadius(type) {
    switch (type) {
      case 'FlaggedTransaction': return 16;
      case 'InvestigationCase': return 14;
      case 'Customer': return 13;
      case 'Card': return 12;
      case 'DeviceProfile': return 11;
      case 'ClosedCase': return 10;
      default: return 9;
    }
  }

  getNodeColor(type) {
    switch (type) {
      case 'FlaggedTransaction': return '#f43f5e'; // Rose
      case 'InvestigationCase': return '#10b981';  // Emerald
      case 'Customer': return '#38bdf8';           // Sky Blue
      case 'Card': return '#6366f1';               // Indigo
      case 'DeviceProfile': return '#06b6d4';      // Cyan
      case 'ClosedCase': return '#a855f7';         // Purple
      case 'ConnectedCard': return '#14b8a6';      // Teal
      case 'Transaction': return '#f59e0b';        // Amber
      default: return '#94a3b8';                   // Slate
    }
  }

  simulate(steps = 1) {
    const k = 0.05; // spring constant
    const repulse = 1200; // repulsion
    const damping = 0.85;

    for (let s = 0; s < steps; s++) {
      // Repulsion between nodes
      for (let i = 0; i < this.nodes.length; i++) {
        for (let j = i + 1; j < this.nodes.length; j++) {
          const n1 = this.nodes[i];
          const n2 = this.nodes[j];
          const dx = n2.x - n1.x;
          const dy = n2.y - n1.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          if (dist < 300) {
            const force = repulse / (dist * dist);
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            n1.vx -= fx;
            n1.vy -= fy;
            n2.vx += fx;
            n2.vy += fy;
          }
        }
      }

      // Spring attraction along links
      for (const link of this.links) {
        const dx = link.target.x - link.source.x;
        const dy = link.target.y - link.source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetDist = 110;
        const force = (dist - targetDist) * k;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        link.source.vx += fx;
        link.source.vy += fy;
        link.target.vx -= fx;
        link.target.vy -= fy;
      }

      // Center gravity
      const cx = this.width / 2;
      const cy = this.height / 2;
      for (const n of this.nodes) {
        n.vx += (cx - n.x) * 0.005;
        n.vy += (cy - n.y) * 0.005;

        n.vx *= damping;
        n.vy *= damping;
        n.x += n.vx;
        n.y += n.vy;
      }
    }
  }

  initEvents() {
    this.canvas.addEventListener('mousedown', e => {
      const pos = this.getCanvasPos(e);
      const clicked = this.findNode(pos.x, pos.y);
      if (clicked) {
        this.dragNode = clicked;
        this.selectedNode = clicked;
        this.render();
        if (window.onNodeSelected) window.onNodeSelected(clicked);
      } else {
        this.isDragging = true;
        this.lastMouse = { x: e.clientX, y: e.clientY };
      }
    });

    window.addEventListener('mousemove', e => {
      if (this.dragNode) {
        const pos = this.getCanvasPos(e);
        this.dragNode.x = pos.x;
        this.dragNode.y = pos.y;
        this.render();
      } else if (this.isDragging) {
        const dx = e.clientX - this.lastMouse.x;
        const dy = e.clientY - this.lastMouse.y;
        this.offsetX += dx;
        this.offsetY += dy;
        this.lastMouse = { x: e.clientX, y: e.clientY };
        this.render();
      } else {
        const pos = this.getCanvasPos(e);
        const hovered = this.findNode(pos.x, pos.y);
        if (hovered !== this.hoveredNode) {
          this.hoveredNode = hovered;
          this.canvas.style.cursor = hovered ? 'pointer' : 'default';
          this.render();
        }
      }
    });

    window.addEventListener('mouseup', () => {
      this.dragNode = null;
      this.isDragging = false;
    });

    this.canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      this.scale = Math.min(Math.max(this.scale * zoomFactor, 0.4), 3.0);
      this.render();
    });
  }

  getCanvasPos(e) {
    const rect = this.canvas.getBoundingClientRect();
    const rawX = e.clientX - rect.left;
    const rawY = e.clientY - rect.top;
    return {
      x: (rawX - this.offsetX) / this.scale,
      y: (rawY - this.offsetY) / this.scale
    };
  }

  findNode(x, y) {
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i];
      const dx = n.x - x;
      const dy = n.y - y;
      if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 4) {
        return n;
      }
    }
    return null;
  }

  resetView() {
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.render();
  }

  zoomIn() {
    this.scale = Math.min(this.scale * 1.2, 3.0);
    this.render();
  }

  zoomOut() {
    this.scale = Math.max(this.scale / 1.2, 0.4);
    this.render();
  }

  render() {
    if (!this.ctx) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.translate(this.offsetX, this.offsetY);
    ctx.scale(this.scale, this.scale);

    // Draw Links
    for (const link of this.links) {
      ctx.beginPath();
      ctx.moveTo(link.source.x, link.source.y);
      ctx.lineTo(link.target.x, link.target.y);
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Link Label
      const mx = (link.source.x + link.target.x) / 2;
      const my = (link.source.y + link.target.y) / 2;
      ctx.font = '8px monospace';
      ctx.fillStyle = '#64748b';
      ctx.textAlign = 'center';
      ctx.fillText(link.type, mx, my - 3);
    }

    // Draw Nodes
    for (const node of this.nodes) {
      const isSelected = this.selectedNode === node;
      const isHovered = this.hoveredNode === node;

      // Glow halo for Flagged or Selected
      if (node.type === 'FlaggedTransaction' || isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 6, 0, Math.PI * 2);
        ctx.fillStyle = node.type === 'FlaggedTransaction' ? 'rgba(244, 63, 94, 0.25)' : 'rgba(56, 189, 248, 0.3)';
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.fill();

      ctx.strokeStyle = isSelected || isHovered ? '#ffffff' : '#0f172a';
      ctx.lineWidth = isSelected ? 2.5 : 1.5;
      ctx.stroke();

      // Node label
      ctx.font = '10px Inter, sans-serif';
      ctx.fillStyle = '#e2e8f0';
      ctx.textAlign = 'center';
      const shortLabel = node.label.length > 20 ? node.label.slice(0, 18) + '…' : node.label;
      ctx.fillText(shortLabel, node.x, node.y + node.radius + 12);
    }

    ctx.restore();
  }
}

window.GraphRenderer = GraphRenderer;

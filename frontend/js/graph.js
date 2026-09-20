/**
 * Interactive Knowledge Graph Renderer using HTML5 Canvas
 * Renders case-scoped entities and relationships with physics layout and node inspection.
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
    this.onNodeSelected = null;

    // Viewport transform
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.isDragging = false;
    this.dragNode = null;
    this.lastMouse = { x: 0, y: 0 };
    this.dragDistance = 0;

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
      this.selectedNode = null;
      this.render();
      if (this.onNodeSelected) this.onNodeSelected(null);
      return;
    }

    const cx = this.width / 2;
    const cy = this.height / 2;

    // Build nodes with initial radial positions around center
    this.nodes = graphData.nodes.map((n, i) => {
      const angle = (i / graphData.nodes.length) * Math.PI * 2;
      const radius = n.type === 'FlaggedTransaction' ? 0 : 130 + (i % 3) * 65;
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

    this.selectedNode = null;
    if (this.onNodeSelected) this.onNodeSelected(null);

    // Run physics layout
    this.simulate(70);
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
      case 'ConnectedCard': return 11;
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
    const k = 0.05;
    const repulse = 1400;
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
          if (dist < 320) {
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
        const targetDist = 120;
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
      this.dragDistance = 0;

      if (clicked) {
        this.dragNode = clicked;
        this.selectedNode = clicked;
        this.render();
        if (this.onNodeSelected) this.onNodeSelected(clicked);
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
        this.dragDistance += 1;
        this.render();
      } else if (this.isDragging) {
        const dx = e.clientX - this.lastMouse.x;
        const dy = e.clientY - this.lastMouse.y;
        this.offsetX += dx;
        this.offsetY += dy;
        this.lastMouse = { x: e.clientX, y: e.clientY };
        this.dragDistance += Math.abs(dx) + Math.abs(dy);
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

    window.addEventListener('mouseup', e => {
      // If user clicked background without dragging, deselect
      if (this.isDragging && this.dragDistance < 4) {
        const pos = this.getCanvasPos(e);
        if (!this.findNode(pos.x, pos.y)) {
          this.selectedNode = null;
          this.render();
          if (this.onNodeSelected) this.onNodeSelected(null);
        }
      }
      this.dragNode = null;
      this.isDragging = false;
    });

    this.canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.12 : 0.88;
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
      if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 6) {
        return n;
      }
    }
    return null;
  }

  resetView() {
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.selectedNode = null;
    this.render();
    if (this.onNodeSelected) this.onNodeSelected(null);
  }

  zoomIn() {
    this.scale = Math.min(this.scale * 1.25, 3.0);
    this.render();
  }

  zoomOut() {
    this.scale = Math.max(this.scale / 1.25, 0.4);
    this.render();
  }

  highlightEntity(entityId) {
    if (!entityId) return;
    const clean = String(entityId).trim().toLowerCase();
    const found = this.nodes.find(n => {
      if (String(n.id).toLowerCase() === clean) return true;
      if (n.metadata) {
        if (String(n.metadata.card_id || '').toLowerCase() === clean) return true;
        if (String(n.metadata.customer_id || '').toLowerCase() === clean) return true;
        if (String(n.metadata.txn_id || '').toLowerCase() === clean) return true;
        if (String(n.metadata.case_id || '').toLowerCase() === clean) return true;
        if (String(n.metadata.full_device || '').toLowerCase().includes(clean)) return true;
      }
      return false;
    });

    if (found) {
      this.selectedNode = found;
      // Smoothly pan so node is in center
      const cx = this.width / 2;
      const cy = this.height / 2;
      this.offsetX = cx - found.x * this.scale;
      this.offsetY = cy - found.y * this.scale;
      this.render();
      if (this.onNodeSelected) this.onNodeSelected(found);
    }
  }

  render() {
    if (!this.ctx) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.translate(this.offsetX, this.offsetY);
    ctx.scale(this.scale, this.scale);

    const hasSelection = !!this.selectedNode;
    const connectedNodeIds = new Set();
    if (hasSelection) {
      connectedNodeIds.add(this.selectedNode.id);
      for (const l of this.links) {
        if (l.source.id === this.selectedNode.id) connectedNodeIds.add(l.target.id);
        if (l.target.id === this.selectedNode.id) connectedNodeIds.add(l.source.id);
      }
    }

    // 1. Draw Links
    for (const link of this.links) {
      const isConnected = hasSelection &&
        (link.source.id === this.selectedNode.id || link.target.id === this.selectedNode.id);

      ctx.beginPath();
      ctx.moveTo(link.source.x, link.source.y);
      ctx.lineTo(link.target.x, link.target.y);

      if (hasSelection) {
        ctx.strokeStyle = isConnected ? '#38bdf8' : 'rgba(51, 65, 85, 0.25)';
        ctx.lineWidth = isConnected ? 2.2 : 1.0;
      } else {
        ctx.strokeStyle = '#334155';
        ctx.lineWidth = 1.5;
      }

      if (link.type === 'SHARED_DEVICE') {
        ctx.setLineDash([4, 4]);
      } else {
        ctx.setLineDash([]);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Link Label
      const mx = (link.source.x + link.target.x) / 2;
      const my = (link.source.y + link.target.y) / 2;
      ctx.font = isConnected ? 'bold 9px monospace' : '8px monospace';
      ctx.fillStyle = isConnected ? '#38bdf8' : (hasSelection ? 'rgba(100, 116, 139, 0.3)' : '#64748b');
      ctx.textAlign = 'center';
      ctx.fillText(link.type, mx, my - 3);
    }

    // 2. Draw Nodes
    for (const node of this.nodes) {
      const isSelected = this.selectedNode === node;
      const isHovered = this.hoveredNode === node;
      const isConnected = hasSelection && connectedNodeIds.has(node.id);
      const isDimmed = hasSelection && !isConnected;

      ctx.globalAlpha = isDimmed ? 0.35 : 1.0;

      // Glow halo for Flagged, Selected, or Hovered
      if (node.type === 'FlaggedTransaction' || isSelected || isHovered) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + (isSelected ? 9 : 6), 0, Math.PI * 2);
        if (node.type === 'FlaggedTransaction') {
          ctx.fillStyle = 'rgba(244, 63, 94, 0.28)';
        } else if (isSelected) {
          ctx.fillStyle = 'rgba(56, 189, 248, 0.35)';
        } else {
          ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
        }
        ctx.fill();
      }

      // Main node circle
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.fill();

      // Node border
      ctx.strokeStyle = isSelected ? '#ffffff' : (isHovered ? '#38bdf8' : '#0f172a');
      ctx.lineWidth = isSelected ? 2.5 : 1.5;
      ctx.stroke();

      // Node label
      ctx.font = isSelected ? 'bold 11px Inter, sans-serif' : '10px Inter, sans-serif';
      ctx.fillStyle = isDimmed ? 'rgba(226, 232, 240, 0.35)' : '#e2e8f0';
      ctx.textAlign = 'center';
      const shortLabel = node.label.length > 22 ? node.label.slice(0, 20) + '…' : node.label;
      ctx.fillText(shortLabel, node.x, node.y + node.radius + 12);
    }

    ctx.globalAlpha = 1.0;
    ctx.restore();
  }
}

window.GraphRenderer = GraphRenderer;

/**
 * HHGOA '26 Interactive Knowledge Graph Renderer using HTML5 Canvas
 * Controlled, sophisticated HHGOA graph palette with high readability.
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

  setTraversalLoading(isLoading, state = {}) {
    this.traversalLoading = !!isLoading;
    this.traversalState = { ...(this.traversalState || {}), ...state };
    if (this.traversalLoading) {
      if (!this._animLoopRunning) {
        this._animLoopRunning = true;
        this._animFrame = 0;
        const tick = () => {
          if (!this.traversalLoading) {
            this._animLoopRunning = false;
            return;
          }
          this._animFrame = (this._animFrame || 0) + 1;
          this.render();
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    } else {
      this._animLoopRunning = false;
      this.render();
    }
  }

  updateTraversalState(state = {}) {
    this.traversalState = { ...(this.traversalState || {}), ...state };
    if (this.traversalLoading && !this._animLoopRunning) {
      this.render();
    }
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

    this.simulate(70);
    this.render();
  }

  getNodeRadius(type) {
    switch (type) {
      case 'FlaggedTransaction': return 16;
      case 'InvestigationCase': return 15;
      case 'Customer': return 14;
      case 'Card': return 13;
      case 'DeviceProfile': return 12;
      case 'ClosedCase': return 11;
      case 'ConnectedCard': return 12;
      default: return 10;
    }
  }

  getNodeColor(type) {
    // Professional Dark Green + Beige palette: minimal semantic colors
    switch (type) {
      case 'FlaggedTransaction': return '#B84A4A'; // Muted Burgundy (Flagged / Risk)
      case 'Customer': return '#F3EBDD';           // Warm Beige (Customer)
      case 'Card': return '#FAF6EC';               // Cream (Card)
      case 'DeviceProfile': return '#6F9F84';      // Muted Green (Device Profile)
      case 'ClosedCase': return '#3F765E';         // Forest Green (Previous Case)
      case 'InvestigationCase': return '#3F765E';  // Forest Green (Case Record)
      case 'ConnectedCard': return '#D8CCB8';      // Muted Beige (Other Txn / Card)
      case 'Transaction': return '#D8CCB8';        // Muted Beige (Other Transaction)
      default: return '#D8CCB8';
    }
  }

  getHumanRelation(type) {
    switch (type) {
      case 'SHARED_DEVICE': return 'Shared Device';
      case 'CC_ON_CARD': return 'Card Used';
      case 'CC_ON_CUSTOMER': return 'Customer Link';
      case 'IC_INVOLVES': return 'Involves';
      case 'OWNS': return 'Owns';
      case 'MADE': return 'Made';
      case 'USED_DEVICE': return 'Device Used';
      default: return (type || '').replace(/_/g, ' ');
    }
  }

  getNodeDisplayParts(node) {
    let typeName = '';
    let idName = '';

    switch (node.type) {
      case 'FlaggedTransaction':
        typeName = 'FLAGGED TXN';
        idName = node.metadata?.txn_id ? `#${node.metadata.txn_id}` : (node.label.replace(/^Flagged Txn:?\s*/i, '') || node.id);
        break;
      case 'Customer':
        typeName = 'CUSTOMER';
        idName = node.metadata?.customer_id || node.label.replace(/^Customer:?\s*/i, '') || node.id;
        break;
      case 'Card':
        typeName = 'CARD';
        idName = node.metadata?.card_id || node.label.replace(/^Card:?\s*/i, '') || node.id;
        break;
      case 'DeviceProfile':
        typeName = 'DEVICE';
        idName = node.metadata?.device_summary || node.label.replace(/^Device:?\s*/i, '') || node.id;
        break;
      case 'ClosedCase':
        typeName = 'PREVIOUS CASE';
        idName = node.metadata?.case_id || node.label.replace(/^Prior Case:?\s*/i, '') || node.id;
        break;
      case 'InvestigationCase':
        typeName = 'CASE RECORD';
        idName = node.metadata?.case_id || node.label.replace(/^Graph Case:?\s*/i, '') || node.id;
        break;
      case 'Transaction':
        typeName = 'TRANSACTION';
        idName = node.metadata?.txn_id ? `#${node.metadata.txn_id}` : (node.label.replace(/^Txn:?\s*/i, '') || node.id);
        break;
      case 'ConnectedCard':
        typeName = 'CARD';
        idName = node.metadata?.card_id || node.label.replace(/^Connected:\s*/i, '') || node.id;
        break;
      default:
        typeName = (node.type || 'ENTITY').toUpperCase();
        idName = node.label || node.id;
    }

    if (idName.length > 22) {
      idName = idName.slice(0, 20) + '…';
    }
    return { typeName, idName };
  }

  simulate(steps = 1) {
    const k = 0.05;
    const repulse = 1400;
    const damping = 0.85;

    for (let s = 0; s < steps; s++) {
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

    if (this.traversalLoading) {
      const cx = this.width / 2;
      const cy = this.height / 2;
      const t = (this._animFrame || 0);

      ctx.save();

      // Subtle, slow pulsating concentric radar circles (ambient scanning state)
      for (let i = 0; i < 3; i++) {
        const radius = ((t * 0.65 + i * 50) % 160) + 25;
        const alpha = Math.max(0, (1 - radius / 185) * 0.2);
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(111, 159, 132, ${alpha})`;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Subtle Traversal HUD Card in the center
      const cardW = 320;
      const cardH = 92;
      const cardX = cx - cardW / 2;
      const cardY = cy - cardH / 2;

      // Card Background (Dark Green)
      ctx.fillStyle = 'rgba(6, 59, 42, 0.94)';
      ctx.beginPath();
      if (ctx.roundRect) {
        ctx.roundRect(cardX, cardY, cardW, cardH, 6);
      } else {
        ctx.rect(cardX, cardY, cardW, cardH);
      }
      ctx.fill();

      // Card Border
      ctx.strokeStyle = 'rgba(216, 204, 184, 0.25)';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Card Header: Title & Progress Pill
      ctx.font = '700 8.5px Inter, sans-serif';
      ctx.fillStyle = '#FAF6EC';
      ctx.textAlign = 'left';
      ctx.fillText('TIGERGRAPH LIVE TRAVERSAL', cardX + 14, cardY + 22);

      const progressText = this.traversalState?.progress || '1/4';
      ctx.font = '700 8.5px JetBrains Mono, monospace';
      ctx.fillStyle = '#D8CCB8';
      ctx.textAlign = 'right';
      ctx.fillText(progressText, cardX + cardW - 14, cardY + 22);

      // Sub-step text
      const subStepText = this.traversalState?.stepText || 'Querying transaction history...';
      ctx.font = '600 10.5px Inter, sans-serif';
      ctx.fillStyle = '#FFF7DD';
      ctx.textAlign = 'left';
      ctx.fillText(subStepText, cardX + 14, cardY + 46);

      // Elapsed status
      const elapsed = this.traversalState?.elapsed || 0;
      ctx.font = '500 8px JetBrains Mono, monospace';
      if (elapsed >= 1.5) {
        ctx.fillStyle = '#C79A32';
        ctx.fillText(`Waiting for TigerGraph... ${elapsed.toFixed(1)}s`, cardX + 14, cardY + 67);
      } else {
        ctx.fillStyle = '#A3B8AD';
        ctx.fillText(`Executing GSQL query traversal (${elapsed.toFixed(1)}s)`, cardX + 14, cardY + 67);
      }

      // Compact slim progress bar (height 3px)
      const barY = cardY + cardH - 10;
      const barW = cardW - 28;
      ctx.fillStyle = 'rgba(216, 204, 184, 0.15)';
      ctx.fillRect(cardX + 14, barY, barW, 3);

      const stepNum = this.traversalState?.step || 1;
      const fillW = Math.min(barW, Math.max(12, (stepNum / 4) * barW));
      ctx.fillStyle = '#3F765E';
      ctx.fillRect(cardX + 14, barY, fillW, 3);

      ctx.restore();
      return;
    }

    if (!this.nodes || this.nodes.length === 0) {
      ctx.save();
      ctx.font = '500 13px Inter, sans-serif';
      ctx.fillStyle = '#D8CCB8';
      ctx.textAlign = 'center';
      ctx.fillText('Case graph will populate upon live investigation execution.', this.width / 2, this.height / 2);
      ctx.restore();
      return;
    }

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

      const isSuspicious = link.type === 'SHARED_DEVICE' || link.type === 'IC_INVOLVES' || link.type === 'CC_ON_CARD';

      ctx.beginPath();
      ctx.moveTo(link.source.x, link.source.y);
      ctx.lineTo(link.target.x, link.target.y);

      if (hasSelection) {
        ctx.strokeStyle = isConnected ? '#FFF7DD' : 'rgba(216, 204, 184, 0.05)';
        ctx.lineWidth = isConnected ? 2.2 : 0.8;
      } else {
        ctx.strokeStyle = isSuspicious ? 'rgba(184, 74, 74, 0.65)' : 'rgba(216, 204, 184, 0.16)';
        ctx.lineWidth = isSuspicious ? 1.5 : 0.9;
      }

      if (link.type === 'SHARED_DEVICE') {
        ctx.setLineDash([4, 4]);
      } else {
        ctx.setLineDash([]);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Link Label (human-readable, only drawn when connected or when suspicious, to eliminate clutter)
      if (isConnected || (!hasSelection && isSuspicious)) {
        const mx = (link.source.x + link.target.x) / 2;
        const my = (link.source.y + link.target.y) / 2;
        const label = this.getHumanRelation(link.type);
        ctx.font = isConnected ? '600 8.5px Inter, sans-serif' : '500 7.5px Inter, sans-serif';
        ctx.fillStyle = isConnected ? '#FFF7DD' : 'rgba(184, 74, 74, 0.75)';
        ctx.textAlign = 'center';
        ctx.fillText(label, mx, my - 2);
      }
    }

    // 2. Draw Nodes
    for (const node of this.nodes) {
      const isSelected = this.selectedNode === node;
      const isHovered = this.hoveredNode === node;
      const isConnected = hasSelection && connectedNodeIds.has(node.id);
      const isDimmed = hasSelection && !isConnected;

      ctx.globalAlpha = isDimmed ? 0.2 : 1.0;

      // Halo for Flagged or Selected
      if (node.type === 'FlaggedTransaction' || isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + (isSelected ? 7 : 5), 0, Math.PI * 2);
        if (node.type === 'FlaggedTransaction') {
          ctx.fillStyle = 'rgba(184, 74, 74, 0.25)';
        } else {
          ctx.fillStyle = 'rgba(255, 247, 221, 0.3)';
        }
        ctx.fill();
      }

      // Main node circle
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.fill();

      // Node border: cream outline #FFF7DD for selected
      ctx.strokeStyle = isSelected ? '#FFF7DD' : (isHovered ? '#FFF7DD' : 'rgba(6, 59, 42, 0.55)');
      ctx.lineWidth = isSelected ? 3.0 : (isHovered ? 2.0 : 1.2);
      ctx.stroke();

      // Node label: Entity TYPE prominently, ID smaller
      const { typeName, idName } = this.getNodeDisplayParts(node);
      const labelAlpha = isDimmed ? 0.18 : (isSelected ? 1.0 : (isConnected ? 0.95 : 0.85));

      ctx.save();
      ctx.globalAlpha = labelAlpha;

      // Prominent Type
      ctx.font = isSelected ? '700 8.5px Inter, sans-serif' : '600 8px Inter, sans-serif';
      ctx.fillStyle = isSelected ? '#FFF7DD' : (node.type === 'FlaggedTransaction' ? '#E8B4B4' : '#FAF6EC');
      ctx.textAlign = 'center';
      ctx.fillText(typeName, node.x, node.y + node.radius + 11);

      // Smaller ID
      ctx.font = isSelected ? '600 7.5px JetBrains Mono, monospace' : '500 7px JetBrains Mono, monospace';
      ctx.fillStyle = isSelected ? '#FAF6EC' : '#D8CCB8';
      ctx.fillText(idName, node.x, node.y + node.radius + 21);

      ctx.restore();
    }

    ctx.globalAlpha = 1.0;
    ctx.restore();
  }
}

window.GraphRenderer = GraphRenderer;

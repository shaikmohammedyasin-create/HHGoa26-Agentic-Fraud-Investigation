/**
 * Interactive Knowledge Graph Renderer using HTML5 Canvas
 * Designed for FraudLens: Dense, Information-Rich, High-Legibility Investigation Graph
 * Color Tokens: Ink Slate, TigerGraph Orange (#F58025), Semantic Fraud/Legit/Unsure
 */

class GraphRenderer {
  constructor(canvasId) {
    this.canvasId = canvasId;
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

    this.traversalLoading = false;
    this.traversalState = null;
    this._animLoopRunning = false;
    this._pulseFrame = 0;

    this.initEvents();
    this.resize();
    window.addEventListener('resize', () => this.resize());
    if (window.ResizeObserver && this.canvas.parentElement) {
      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(this.canvas.parentElement);
    }
  }

  resize() {
    if (!this.canvas || !this.canvas.parentElement) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = this.width * window.devicePixelRatio;
    this.canvas.height = this.height * window.devicePixelRatio;
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    if (this.nodes && this.nodes.length > 0) {
      this.fitToView(true);
    } else {
      this.render();
    }
  }

  setTraversalLoading(isLoading, state = {}) {
    this.traversalLoading = !!isLoading;
    this.traversalState = { ...(this.traversalState || {}), ...state };
    if (this.traversalLoading) {
      if (!this._animLoopRunning) {
        this._animLoopRunning = true;
        const tick = () => {
          if (!this.traversalLoading) {
            this._animLoopRunning = false;
            return;
          }
          this._pulseFrame = (this._pulseFrame || 0) + 1;
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
    if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
      this.nodes = [];
      this.links = [];
      this.selectedNode = null;
      this.render();
      if (this.onNodeSelected) this.onNodeSelected(null);
      return;
    }

    const rect = this.canvas.parentElement ? this.canvas.parentElement.getBoundingClientRect() : null;
    if (rect && rect.width > 0 && rect.height > 0) {
      this.width = rect.width;
      this.height = rect.height;
      this.canvas.width = this.width * window.devicePixelRatio;
      this.canvas.height = this.height * window.devicePixelRatio;
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    } else {
      this.width = this.width || 760;
      this.height = this.height || 540;
    }

    const cx = this.width / 2;
    const cy = this.height / 2;

    // Topological semantic layout matching FraudLens
    let flagged = null, card = null, customer = null, dev = null;
    const otherTxns = [], connCards = [], closedCases = [], otherNodes = [];

    graphData.nodes.forEach(n => {
      if (n.type === 'FlaggedTransaction') flagged = n;
      else if (n.type === 'Card' && !card) card = n;
      else if (n.type === 'Customer' && !customer) customer = n;
      else if (n.type === 'DeviceProfile' && !dev) dev = n;
      else if (n.type === 'ConnectedCard') connCards.push(n);
      else if (n.type === 'Transaction') otherTxns.push(n);
      else if (n.type === 'ClosedCase') closedCases.push(n);
      else otherNodes.push(n);
    });

    const nodes = [];
    const addNode = (n, x, y) => {
      if (!n) return;
      const s = this.getNodeStyle(n.type);
      nodes.push({
        ...n,
        x, y,
        vx: 0, vy: 0,
        radius: s.radius,
        width: s.w,
        height: s.h,
        shape: s.shape,
        color: s.color,
        label: n.label || n.id,
      });
    };

    // Central topological layout
    addNode(flagged, cx, cy);
    addNode(card, cx - 110, cy - 50);
    addNode(customer, cx - 210, cy - 100);
    addNode(dev, cx + 130, cy + 20);

    // 48h transactions clustered around card
    otherTxns.forEach((t, i) => {
      const a = -Math.PI / 2 + (i / Math.max(1, otherTxns.length)) * Math.PI;
      addNode(t, (cx - 110) + Math.cos(a) * 85, (cy - 50) + Math.sin(a) * 85);
    });

    // Connected syndicate cards fan out to right from DeviceProfile
    connCards.forEach((c, i) => {
      const a = -Math.PI / 2.2 + (i / Math.max(1, connCards.length - 1 || 1)) * (Math.PI * 0.9);
      const r = 115 + (i % 2) * 35;
      addNode(c, (cx + 130) + Math.cos(a) * r, (cy + 20) + Math.sin(a) * r);
    });

    // Closed cases fan out to top-left from Customer
    closedCases.forEach((c, i) => {
      const a = Math.PI * 0.75 + (i / Math.max(1, closedCases.length - 1 || 1)) * (Math.PI * 0.6);
      addNode(c, (cx - 210) + Math.cos(a) * 95, (cy - 100) + Math.sin(a) * 95);
    });

    // Remaining nodes (InvestigationCase etc.)
    otherNodes.forEach((o, i) => {
      const a = (i / Math.max(1, otherNodes.length)) * Math.PI * 2;
      addNode(o, cx + Math.cos(a) * 170, cy + Math.sin(a) * 170);
    });

    this.nodes = nodes;

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

    // Stabilize layout with quick physics relaxation
    this.stepPhysics(120);
    this.fitToView(true);
  }

  getNodeStyle(type) {
    // Official FraudLens visual mapping: color, shape, dimensions
    switch (type) {
      case 'Transaction':
        return { color: '#5EA8FF', shape: 'round-rect', w: 22, h: 18, radius: 12, label: 'Transaction' };
      case 'Card':
        return { color: '#D7DEE8', shape: 'round-rect', w: 32, h: 22, radius: 15, label: 'Card' };
      case 'Customer':
        return { color: '#A48BFA', shape: 'ellipse', w: 28, h: 28, radius: 14, label: 'Customer' };
      case 'DeviceProfile':
        return { color: '#2FD3BE', shape: 'hexagon', w: 34, h: 30, radius: 16, label: 'Device profile' };
      case 'ClosedCase':
        return { color: '#F277B5', shape: 'diamond', w: 26, h: 26, radius: 14, label: 'Closed case' };
      case 'InvestigationCase':
        return { color: '#F58025', shape: 'star', w: 32, h: 32, radius: 17, label: 'Investigation' };
      case 'ConnectedCard':
        return { color: '#06B6D4', shape: 'round-rect', w: 30, h: 20, radius: 14, label: 'Connected Card' };
      case 'FlaggedTransaction':
        return { color: '#EF5A50', shape: 'flagged-pulse', w: 34, h: 30, radius: 18, label: 'Flagged Txn' };
      default:
        return { color: '#96A1B3', shape: 'ellipse', w: 22, h: 22, radius: 11, label: 'Entity' };
    }
  }

  getHumanRelation(type) {
    switch (type) {
      case 'SHARED_DEVICE': return 'Shared Device';
      case 'CC_ON_CARD': return 'Card History';
      case 'CC_ON_CUSTOMER': return 'Customer Case';
      case 'IC_INVOLVES': return 'Involves';
      case 'IC_ON_CARD': return 'On Card';
      case 'IC_FOR_CUSTOMER': return 'For Customer';
      case 'OWNS': return 'Owns';
      case 'MADE': return 'Made';
      case 'FROM_DEVICE': return 'From Device';
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
        typeName = 'PRIOR CASE';
        idName = node.metadata?.case_id || node.label.replace(/^Prior Case:?\s*/i, '') || node.id;
        break;
      case 'InvestigationCase':
        typeName = 'GRAPH CASE';
        idName = node.metadata?.case_id || node.label.replace(/^Graph Case:?\s*/i, '') || node.id;
        break;
      case 'Transaction':
        typeName = 'TRANSACTION';
        idName = node.metadata?.txn_id ? `#${node.metadata.txn_id}` : (node.label.replace(/^Txn:?\s*/i, '') || node.id);
        break;
      case 'ConnectedCard':
        typeName = 'LINKED CARD';
        idName = node.metadata?.card_id || node.label.replace(/^Connected:\s*/i, '') || node.id;
        break;
      default:
        typeName = (node.type || 'ENTITY').toUpperCase();
        idName = node.label || node.id;
    }

    if (idName.length > 20) {
      idName = idName.slice(0, 18) + '…';
    }
    return { typeName, idName };
  }

  stepPhysics(steps = 1) {
    if (!this.nodes || this.nodes.length === 0) return;

    const cx = this.width / 2;
    const cy = this.height / 2;
    const repulseStrength = 4200;
    const springK = 0.045;
    const damping = 0.84;

    for (let s = 0; s < steps; s++) {
      for (let i = 0; i < this.nodes.length; i++) {
        for (let j = i + 1; j < this.nodes.length; j++) {
          const n1 = this.nodes[i];
          const n2 = this.nodes[j];
          const dx = n2.x - n1.x;
          const dy = n2.y - n1.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const minDist = (n1.radius || 15) + (n2.radius || 15) + 30;

          if (dist < minDist * 2.5) {
            const force = (repulseStrength / (dist * dist + 100));
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
        const desired = 95;
        const delta = dist - desired;
        const fx = (dx / dist) * delta * springK;
        const fy = (dy / dist) * delta * springK;

        link.source.vx += fx;
        link.source.vy += fy;
        link.target.vx -= fx;
        link.target.vy -= fy;
      }

      for (const n of this.nodes) {
        if (n.type === 'FlaggedTransaction') {
          n.vx += (cx - n.x) * 0.08;
          n.vy += (cy - n.y) * 0.08;
        } else {
          n.vx += (cx - n.x) * 0.008;
          n.vy += (cy - n.y) * 0.008;
        }

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
      this.scale = Math.min(Math.max(this.scale * zoomFactor, 0.35), 3.0);
      this.render();
    });
  }

  fitToView(render = true) {
    if (!this.nodes || this.nodes.length === 0) return;
    if (!this.width || !this.height) return;

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of this.nodes) {
      const r = n.radius || 15;
      minX = Math.min(minX, n.x - Math.max(r, 45));
      maxX = Math.max(maxX, n.x + Math.max(r, 45));
      minY = Math.min(minY, n.y - r);
      maxY = Math.max(maxY, n.y + r + 26);
    }

    const bw = Math.max(60, maxX - minX);
    const bh = Math.max(60, maxY - minY);
    const midX = (minX + maxX) / 2;
    const midY = (minY + maxY) / 2;

    const padTop = 50;
    const padBottom = 50;
    const padX = 50;

    const availW = Math.max(100, this.width - padX * 2);
    const availH = Math.max(100, this.height - (padTop + padBottom));

    const fitScale = Math.min(availW / bw, availH / bh);
    this.scale = Math.max(0.65, Math.min(1.25, fitScale));

    const effectiveCenterY = padTop + availH / 2;
    this.offsetX = (this.width / 2) - midX * this.scale;
    this.offsetY = effectiveCenterY - midY * this.scale;

    if (render) {
      this.render();
    }
  }

  resetView() {
    this.fitToView(true);
    this.selectedNode = null;
    if (this.onNodeSelected) this.onNodeSelected(null);
  }

  zoomIn() {
    this.scale = Math.min(this.scale * 1.25, 3.0);
    this.render();
  }

  zoomOut() {
    this.scale = Math.max(this.scale / 1.25, 0.35);
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
      }
      return false;
    });

    if (found) {
      this.selectedNode = found;
      this.render();
      if (this.onNodeSelected) this.onNodeSelected(found);
    }
  }

  getCanvasPos(e) {
    const rect = this.canvas.getBoundingClientRect();
    const clientX = e.clientX - rect.left;
    const clientY = e.clientY - rect.top;
    return {
      x: (clientX - this.offsetX) / this.scale,
      y: (clientY - this.offsetY) / this.scale
    };
  }

  findNode(x, y) {
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i];
      const dx = x - n.x;
      const dy = y - n.y;
      const hitRadius = Math.max(n.radius || 15, 20);
      if (dx * dx + dy * dy <= hitRadius * hitRadius) {
        return n;
      }
    }
    return null;
  }

  render() {
    const ctx = this.ctx;
    if (!ctx) return;

    ctx.clearRect(0, 0, this.width, this.height);

    // 1. Subtle Background Grid (Graph coordinate paper)
    ctx.save();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.025)';
    ctx.lineWidth = 1;
    const gridSize = 32 * this.scale;
    const startX = this.offsetX % gridSize;
    const startY = this.offsetY % gridSize;

    for (let x = startX; x < this.width; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, this.height);
      ctx.stroke();
    }
    for (let y = startY; y < this.height; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(this.width, y);
      ctx.stroke();
    }
    ctx.restore();

    // 2. Traversal Live Radar HUD
    if (this.traversalLoading) {
      const cx = this.width / 2;
      const cy = this.height / 2;
      const t = this._pulseFrame || 0;

      ctx.save();
      for (let i = 0; i < 3; i++) {
        const radius = ((t * 0.7 + i * 50) % 170) + 20;
        const alpha = Math.max(0, (1 - radius / 190) * 0.3);
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(245, 128, 37, ${alpha})`;
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      // Live Traversal HUD Box
      const cardW = 320;
      const cardH = 92;
      const cardX = cx - cardW / 2;
      const cardY = cy - cardH / 2;

      ctx.fillStyle = 'rgba(14, 18, 24, 0.95)';
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(cardX, cardY, cardW, cardH, 8);
      else ctx.rect(cardX, cardY, cardW, cardH);
      ctx.fill();

      ctx.strokeStyle = 'rgba(245, 128, 37, 0.45)';
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.font = '700 9px Inter, sans-serif';
      ctx.fillStyle = '#E7EBF1';
      ctx.textAlign = 'left';
      ctx.fillText('LIVE GRAPH TRAVERSAL', cardX + 16, cardY + 24);

      const progressText = this.traversalState?.progress || '1/4';
      ctx.font = '700 9px JetBrains Mono, monospace';
      ctx.fillStyle = '#F58025';
      ctx.textAlign = 'right';
      ctx.fillText(progressText, cardX + cardW - 16, cardY + 24);

      const subStepText = this.traversalState?.stepText || 'Querying transaction history...';
      ctx.font = '600 11px Inter, sans-serif';
      ctx.fillStyle = '#F89A50';
      ctx.textAlign = 'left';
      ctx.fillText(subStepText, cardX + 16, cardY + 48);

      const elapsed = this.traversalState?.elapsed || 0;
      ctx.font = '500 9px JetBrains Mono, monospace';
      ctx.fillStyle = '#96A1B3';
      ctx.fillText(`Executing GSQL query traversal (${elapsed.toFixed(1)}s)`, cardX + 16, cardY + 68);

      const barY = cardY + cardH - 10;
      const barW = cardW - 32;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
      ctx.fillRect(cardX + 16, barY, barW, 3);

      const stepNum = this.traversalState?.step || 1;
      const fillW = Math.min(barW, Math.max(12, (stepNum / 4) * barW));
      ctx.fillStyle = '#F58025';
      ctx.fillRect(cardX + 16, barY, fillW, 3);

      ctx.restore();
      return;
    }

    if (!this.nodes || this.nodes.length === 0) {
      ctx.save();
      ctx.font = '500 12.5px Inter, sans-serif';
      ctx.fillStyle = '#6A7688';
      ctx.textAlign = 'center';
      ctx.fillText('Case graph will populate upon live investigation execution.', this.width / 2, this.height / 2);
      ctx.restore();
      return;
    }

    ctx.save();
    ctx.translate(this.offsetX, this.offsetY);
    ctx.scale(this.scale, this.scale);

    // Neighborhood isolation for hover/selection
    const activeFocus = this.selectedNode || this.hoveredNode;
    const focusNeighbors = new Set();
    if (activeFocus) {
      focusNeighbors.add(activeFocus.id);
      for (const l of this.links) {
        if (l.source.id === activeFocus.id) focusNeighbors.add(l.target.id);
        if (l.target.id === activeFocus.id) focusNeighbors.add(l.source.id);
      }
    }

    // 3. Draw Links (Edges)
    for (const link of this.links) {
      const isIncident = activeFocus && (link.source.id === activeFocus.id || link.target.id === activeFocus.id);
      const isDimmed = activeFocus && !isIncident;
      const isRing = link.type === 'SHARED_DEVICE';

      ctx.beginPath();
      ctx.moveTo(link.source.x, link.source.y);
      ctx.lineTo(link.target.x, link.target.y);

      if (isDimmed) {
        ctx.strokeStyle = 'rgba(31, 39, 51, 0.4)';
        ctx.lineWidth = 0.8;
      } else if (isIncident) {
        ctx.strokeStyle = '#F58025';
        ctx.lineWidth = 2.2;
      } else if (isRing) {
        ctx.strokeStyle = '#8A3B35';
        ctx.lineWidth = 1.4;
      } else {
        ctx.strokeStyle = '#344052';
        ctx.lineWidth = 1.2;
      }
      ctx.stroke();

      // Draw subtle edge label on incident or hover
      if (isIncident || !activeFocus) {
        const mx = (link.source.x + link.target.x) / 2;
        const my = (link.source.y + link.target.y) / 2;
        const relText = this.getHumanRelation(link.type);

        ctx.font = '600 7.5px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        ctx.fillStyle = isIncident ? '#FBB27A' : '#6A7688';
        ctx.fillText(relText, mx, my - 3);
      }
    }

    // 4. Draw Nodes
    for (const node of this.nodes) {
      const isSelected = this.selectedNode && this.selectedNode.id === node.id;
      const isHovered = this.hoveredNode && this.hoveredNode.id === node.id;
      const isNeighbor = activeFocus && focusNeighbors.has(node.id);
      const isDimmed = activeFocus && !isNeighbor;

      ctx.save();
      ctx.translate(node.x, node.y);

      if (isDimmed) {
        ctx.globalAlpha = 0.25;
      }

      // Selection / Flagged Halo
      if (isSelected || isHovered) {
        ctx.beginPath();
        ctx.arc(0, 0, (node.radius || 15) + 6, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(245, 128, 37, 0.22)';
        ctx.fill();
        ctx.strokeStyle = '#F58025';
        ctx.lineWidth = 1.8;
        ctx.stroke();
      } else if (node.type === 'FlaggedTransaction') {
        const pulseR = (node.radius || 16) + 4;
        ctx.beginPath();
        ctx.arc(0, 0, pulseR, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(239, 90, 80, 0.2)';
        ctx.fill();
      }

      // Draw Shape based on style
      this.drawNodeShape(ctx, node);

      // Node Label Text Below
      const { typeName, idName } = this.getNodeDisplayParts(node);
      const isHighlighted = isSelected || isHovered || isNeighbor;

      ctx.font = '700 7.5px Inter, sans-serif';
      ctx.fillStyle = isHighlighted ? '#F58025' : '#6A7688';
      ctx.textAlign = 'center';
      ctx.fillText(typeName, 0, (node.radius || 15) + 12);

      ctx.font = '600 8.5px JetBrains Mono, monospace';
      ctx.fillStyle = isHighlighted ? '#FFFFFF' : '#C3CBD7';
      ctx.fillText(idName, 0, (node.radius || 15) + 22);

      ctx.restore();
    }

    ctx.restore();
  }

  drawNodeShape(ctx, node) {
    const s = this.getNodeStyle(node.type);
    const color = s.color;
    const w = s.w;
    const h = s.h;

    ctx.fillStyle = color;
    ctx.strokeStyle = '#06080B';
    ctx.lineWidth = 1.6;

    switch (s.shape) {
      case 'ellipse':
        ctx.beginPath();
        ctx.arc(0, 0, w / 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        break;

      case 'round-rect':
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(-w / 2, -h / 2, w, h, 4);
        else ctx.rect(-w / 2, -h / 2, w, h);
        ctx.fill();
        ctx.stroke();
        break;

      case 'hexagon':
        ctx.beginPath();
        const r = w / 2;
        for (let i = 0; i < 6; i++) {
          const a = (Math.PI / 3) * i;
          const x = r * Math.cos(a);
          const y = r * Math.sin(a);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        break;

      case 'diamond':
        ctx.beginPath();
        ctx.moveTo(0, -h / 2);
        ctx.lineTo(w / 2, 0);
        ctx.lineTo(0, h / 2);
        ctx.lineTo(-w / 2, 0);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        break;

      case 'star':
        ctx.beginPath();
        const spikes = 5;
        const outerR = w / 2;
        const innerR = outerR * 0.45;
        let rot = Math.PI / 2 * 3;
        let step = Math.PI / spikes;
        ctx.moveTo(0, -outerR);
        for (let i = 0; i < spikes; i++) {
          let x = Math.cos(rot) * outerR;
          let y = Math.sin(rot) * outerR;
          ctx.lineTo(x, y);
          rot += step;
          x = Math.cos(rot) * innerR;
          y = Math.sin(rot) * innerR;
          ctx.lineTo(x, y);
          rot += step;
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        break;

      case 'flagged-pulse':
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(-w / 2, -h / 2, w, h, 5);
        else ctx.rect(-w / 2, -h / 2, w, h);
        ctx.fill();
        ctx.strokeStyle = '#FFE2CC';
        ctx.lineWidth = 2.2;
        ctx.stroke();
        break;

      default:
        ctx.beginPath();
        ctx.arc(0, 0, (node.radius || 12), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
    }
  }
}

window.GraphRenderer = GraphRenderer;

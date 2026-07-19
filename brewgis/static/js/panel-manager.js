/**
 * Panel Manager — controls map shell panels (sidebar, right panel, bottom sheet, modal).
 * Loaded as a deferred script in workspace_map.html.
 */
(function () {
  'use strict';

  // ─── State ─────────────────────────────────────────────────
  var state = {
    leftSidebarOpen: false,
    rightPanelOpen: false,
    bottomSheetOpen: false,
    modalOpen: false,
    activePanel: null,
    panelTitle: '',
  };

  if (typeof window.__panelState === 'undefined') {
    window.__panelState = state;
  } else {
    state = window.__panelState;
  }

  // ─── DOM refs ──────────────────────────────────────────────
  function getMapEl() {
    return document.querySelector('brew-gis-map');
  }

  // ─── Left Sidebar ──────────────────────────────────────────
  function toggleSidebar() {
    var sidebar = document.getElementById('left-sidebar');
    if (!sidebar) return;

    var isCollapsed = sidebar.classList.contains('collapsed');
    sidebar.classList.toggle('collapsed');
    state.leftSidebarOpen = !isCollapsed;

    // When expanding, load layer list via htmx
    if (state.leftSidebarOpen) {
      var content = document.getElementById('left-sidebar-content');
      if (content && !content.hasChildNodes()) {
        var wsId = document.getElementById('left-sidebar')?.getAttribute('data-workspace-pk');
        if (wsId) {
          htmx.ajax('GET', '/workspace/' + wsId + '/panel/layer-list/', {
            target: '#left-sidebar-content',
            swap: 'innerHTML',
          });
        }
      }
    }
  }

  function setSidebarTab(name) {
    var content = document.getElementById('left-sidebar-content');
    if (!content) return;

    var wsId = document.getElementById('left-sidebar')?.getAttribute('data-workspace-pk');
    if (!wsId) return;

    var urls = {
      layers: '/workspace/' + wsId + '/panel/layer-list/',
      catalog: '/workspace/' + wsId + '/panel/catalog/',
      import: '/workspace/' + wsId + '/panel/import/',
      analysis: '/workspace/' + wsId + '/panel/analysis/',
      reports: '/workspace/' + wsId + '/panel/reports/',
    };

    var url = urls[name];
    if (url) {
      htmx.ajax('GET', url, { target: '#left-sidebar-content', swap: 'innerHTML' });
      state.activePanel = name;
    }

    // Update active icon state
    document.querySelectorAll('.sidebar-icons button').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-panel') === name);
    });

    // Expand sidebar if collapsed
    var sidebarEl = document.getElementById('left-sidebar');
    if (sidebarEl && sidebarEl.classList.contains('collapsed')) {
      toggleSidebar();
    }
  }

  // ─── Right Panel ───────────────────────────────────────────
  function openPanel(title, contentHtml) {
    var panel = document.getElementById('right-panel');
    var titleEl = document.getElementById('right-panel-title');
    var contentEl = document.getElementById('right-panel-content');
    if (!panel || !titleEl || !contentEl) return;

    titleEl.textContent = title;
    if (contentHtml) {
      contentEl.innerHTML = contentHtml;
    }
    panel.classList.add('open');
    state.rightPanelOpen = true;
    state.panelTitle = title;

    // Update map padding
    updateMapPadding();
  }

  function closePanel() {
    var panel = document.getElementById('right-panel');
    if (!panel) return;

    panel.classList.remove('open');
    state.rightPanelOpen = false;
    state.panelTitle = '';

    // Reset map padding
    updateMapPadding();

    document.body.dispatchEvent(new CustomEvent('panel-closed', { detail: { side: 'right' } }));
  }

  // ─── Bottom Sheet ──────────────────────────────────────────
  function openSheet(title, contentHtml) {
    var sheet = document.getElementById('bottom-sheet');
    var titleEl = document.getElementById('bottom-sheet-title');
    var contentEl = document.getElementById('bottom-sheet-content');
    if (!sheet || !titleEl || !contentEl) return;

    titleEl.textContent = title;
    if (contentHtml) {
      contentEl.innerHTML = contentHtml;
    }
    sheet.classList.add('open');
    state.bottomSheetOpen = true;
    state.panelTitle = title;

    // Update map padding
    updateMapPadding();
  }

  function closeSheet() {
    var sheet = document.getElementById('bottom-sheet');
    if (!sheet) return;

    sheet.classList.remove('open');
    state.bottomSheetOpen = false;
    state.panelTitle = '';

    // Reset map padding
    updateMapPadding();

    document.body.dispatchEvent(new CustomEvent('panel-closed', { detail: { side: 'bottom' } }));
  }

  // ─── Modal ─────────────────────────────────────────────────
  function openModal(contentHtml) {
    var backdrop = document.getElementById('modal-container');
    var contentEl = document.getElementById('modal-content');
    if (!backdrop || !contentEl) return;

    if (contentHtml) {
      contentEl.innerHTML = contentHtml;
    }
    backdrop.classList.add('open');
    state.modalOpen = true;
  }

  function closeModal() {
    var backdrop = document.getElementById('modal-container');
    if (!backdrop) return;

    backdrop.classList.remove('open');
    state.modalOpen = false;

    document.body.dispatchEvent(new CustomEvent('panel-closed', { detail: { side: 'modal' } }));
  }

  // ─── Map Integration ──────────────────────────────────────
  function updateMapPadding() {
    var mapEl = getMapEl();
    if (!mapEl) return;

    if (state.rightPanelOpen) {
      mapEl.panelSide = 'right';
      mapEl.panelWidth = 400;
    } else if (state.bottomSheetOpen) {
      mapEl.panelSide = 'bottom';
      mapEl.panelWidth = Math.round(window.innerHeight * 0.4);
    } else {
      mapEl.panelSide = null;
      mapEl.panelWidth = 0;
    }
  }

  // ResizeObserver for map element resizing
  var mapResizeObserver = null;

  function setupMapResizeObserver() {
    var mapContainer = document.querySelector('.map-shell__map');
    if (!mapContainer) return;

    mapResizeObserver = new ResizeObserver(function () {
      var mapEl = getMapEl();
      if (mapEl && typeof mapEl.resize === 'function') {
        mapEl.resize();
      }
    });
    mapResizeObserver.observe(mapContainer);
  }

  // ─── Keyboard ─────────────────────────────────────────────
  function handleKeydown(e) {
    if (e.key !== 'Escape') return;

    if (state.modalOpen) {
      closeModal();
      e.preventDefault();
    } else if (state.rightPanelOpen) {
      closePanel();
      e.preventDefault();
    } else if (state.bottomSheetOpen) {
      closeSheet();
      e.preventDefault();
    } else if (state.leftSidebarOpen) {
      toggleSidebar();
      e.preventDefault();
    }
  }

  // ─── Click-outside ────────────────────────────────────────
  function handleMapClick(e) {
    // Close right panel on map area click
    if (state.rightPanelOpen && e.target.closest('.map-shell__map')) {
      closePanel();
    }
  }

  function handleModalBackdropClick(e) {
    if (state.modalOpen && e.target === e.currentTarget) {
      closeModal();
    }
  }

  // ─── htmx Event Bridge ────────────────────────────────────
  function handleHtmxAfterSettle(evt) {
    var panelEvent = evt.detail.target?.getAttribute('data-panel-event');
    if (!panelEvent) return;

    if (panelEvent === 'close-panel') {
      closePanel();
    } else if (panelEvent === 'close-sheet') {
      closeSheet();
    } else if (panelEvent === 'close-modal') {
      closeModal();
    } else if (panelEvent.startsWith('open-panel:')) {
      var title = panelEvent.substring('open-panel:'.length);
      openPanel(title);
    } else if (panelEvent.startsWith('open-sheet:')) {
      var sheetTitle = panelEvent.substring('open-sheet:'.length);
      openSheet(sheetTitle);
    }
  }

  // ─── Window Resize ────────────────────────────────────────
  var resizeTimer = null;

  function handleResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      updateMapPadding();

      var mapEl = getMapEl();
      if (mapEl && typeof mapEl.resize === 'function') {
        mapEl.resize();
      }
    }, 150);
  }

  // ─── Init ──────────────────────────────────────────────────
  function init() {
    // Wire sidebar toggle
    var sidebarToggle = document.getElementById('sidebar-toggle');
    if (sidebarToggle) {
      sidebarToggle.addEventListener('click', toggleSidebar);
    }

    // Wire sidebar icon buttons
    document.querySelectorAll('.sidebar-icons button[data-panel]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setSidebarTab(this.getAttribute('data-panel'));
      });
    });

    // Wire right panel close
    var rightPanelClose = document.getElementById('right-panel-close');
    if (rightPanelClose) {
      rightPanelClose.addEventListener('click', closePanel);
    }

    // Wire bottom sheet close
    var bottomSheetClose = document.getElementById('bottom-sheet-close');
    if (bottomSheetClose) {
      bottomSheetClose.addEventListener('click', closeSheet);
    }

    // Wire modal backdrop click
    var modalBackdrop = document.getElementById('modal-container');
    if (modalBackdrop) {
      modalBackdrop.addEventListener('click', handleModalBackdropClick);
    }

    // Keyboard handler
    document.addEventListener('keydown', handleKeydown);

    // Map area click handler
    document.querySelector('.map-shell')?.addEventListener('click', handleMapClick);

    // htmx event bridge
    document.body.addEventListener('htmx:afterSettle', handleHtmxAfterSettle);

    // Window resize
    window.addEventListener('resize', handleResize);

    // Map resize observer
    setupMapResizeObserver();

    // ─── Symbology preview (Step 2) ──────────────────────────
    document.body.addEventListener('layer-style-preview', function(evt) {
      var detail = evt.detail;
      if (!detail || !detail.layerKey || !detail.paint) return;
      var mapEl = getMapEl();
      if (!mapEl) return;
      var map = mapEl._map || mapEl['_map'];
      if (!map) return;
      var style = map.getStyle();
      if (!style || !style.layers) return;
      var targetLayer = style.layers.find(function(l) {
        return l.id.indexOf(detail.layerKey) === 0;
      });
      if (!targetLayer) {
        console.warn('No MapLibre layer found for key:', detail.layerKey);
        return;
      }
      if (typeof mapEl.previewLayerStyle === 'function') {
        mapEl.previewLayerStyle(targetLayer.id, detail.paint);
      }
    });

    // ─── Symbology saved / auto-generated (Steps 3, 5) ──────
    document.body.addEventListener('layer-style-changed', function(evt) {
      var detail = evt.detail;
      if (!detail || !detail.layerKey || !detail.style) return;
      var mapEl = getMapEl();
      if (!mapEl) return;
      var map = mapEl._map || mapEl['_map'];
      if (!map) return;
      var style = map.getStyle();
      if (!style || !style.layers) return;
      var targetLayer = style.layers.find(function(l) {
        return l.id.indexOf(detail.layerKey) === 0;
      });
      if (!targetLayer) return;
      // Apply paint and layout properties
      if (detail.style.paint && typeof mapEl.previewLayerStyle === 'function') {
        mapEl.previewLayerStyle(targetLayer.id, detail.style.paint);
      }
      if (detail.style.layout) {
        for (var key in detail.style.layout) {
          try { map.setLayoutProperty(targetLayer.id, key, detail.style.layout[key]); } catch(e) {}
        }
      }
    });

    // ─── Toast messages ─────────────────────────────────────
    document.body.addEventListener('show-toast', function(evt) {
      var msg = evt.detail;
      if (!msg) return;
      var toast = document.getElementById('toast-container');
      if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast-container';
        toast.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;';
        document.body.appendChild(toast);
      }
      var el = document.createElement('div');
      el.className = 'alert alert-info alert-dismissible fade show py-1 px-2 mb-1';
      el.style.fontSize = '0.75rem';
      el.textContent = typeof msg === 'string' ? msg : msg.toString();
      var closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'btn-close py-1';
      closeBtn.style.fontSize = '0.6rem';
      closeBtn.onclick = function() { el.remove(); };
      el.appendChild(closeBtn);
      toast.appendChild(el);
      setTimeout(function() { el.remove(); }, 4000);
    });

    // Expose panel API globally for htmx response handlers and inline scripts
    window.__panelManager = {
      openPanel: openPanel,
      closePanel: closePanel,
      openSheet: openSheet,
      closeSheet: closeSheet,
      openModal: openModal,
      closeModal: closeModal,
      toggleSidebar: toggleSidebar,
      setSidebarTab: setSidebarTab,
    };
  }

  // Wait for DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

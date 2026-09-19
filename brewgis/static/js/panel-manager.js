/**
 * Panel Manager — controls map shell panels (sidebar, right panel, bottom sheet, modal).
 * Loaded as a deferred script in workspace_map.html.
 *
 * Open/close state lives in the Alpine store 'panels' (registered below via
 * 'alpine:init'), so workspace_map.html's x-bind/x-on/x-text directives can
 * react to it directly instead of this file manually toggling classes and
 * text content. window.__panelManager stays as a thin compatibility shim
 * forwarding to the store, since several server-rendered partials — loaded
 * via htmx into these same panels — still call it from plain onclick
 * handlers or data-panel-event attributes rather than Alpine bindings.
 */
(function () {
  'use strict';

  // ─── DOM refs ──────────────────────────────────────────────
  function getMapEl() {
    return document.querySelector('brew-gis-map');
  }

  document.addEventListener('alpine:init', function () {
    Alpine.store('panels', {
      leftSidebarOpen: false,
      activePanel: 'layers',
      sidebarWide: false,

      rightPanelOpen: false,
      rightPanelWide: false,
      rightPanelTitle: '',

      bottomSheetOpen: false,
      sheetTitle: '',

      modalOpen: false,

      // Layer whose symbology editor is currently showing in the right
      // panel, if any — live-preview edits (layer-style-preview) mutate the
      // map directly without saving, so whenever this layer's editor goes
      // away without a save (Cancel, X, Escape, click-outside, or
      // navigating to a different panel), its actually-saved style must be
      // re-fetched and reapplied to undo any lingering unsaved preview.
      symbologyPreviewLayerPk: null,
      symbologyPreviewLayerKey: null,

      // ─── Left Sidebar ────────────────────────────────────
      toggleSidebar: function () {
        this.leftSidebarOpen = !this.leftSidebarOpen;

        // When expanding, load layer list via htmx
        if (this.leftSidebarOpen) {
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
      },

      setSidebarTab: function (name) {
        // Clicking the icon of the tab that is already showing collapses the
        // sidebar — same result as the ☰ button, so an icon both opens and
        // closes its panel instead of only ever opening it.
        if (this.leftSidebarOpen && this.activePanel === name) {
          this.leftSidebarOpen = false;
          return;
        }

        var content = document.getElementById('left-sidebar-content');
        if (!content) return;

        var wsId = document.getElementById('left-sidebar')?.getAttribute('data-workspace-pk');
        if (!wsId) return;

        // The map's active scenario (if any) is carried via ?scenario= so
        // panel views can default to its data (e.g. the Analysis panel
        // defaulting "Parcel Table" to the scenario's canvas view instead
        // of the raw, unpainted base table).
        var scenarioId = getMapEl()?.getAttribute('scenario-id');
        var scenarioQuery = scenarioId ? '?scenario=' + encodeURIComponent(scenarioId) : '';

        var urls = {
          layers: '/workspace/' + wsId + '/panel/layer-list/' + scenarioQuery,
          catalog: '/workspace/' + wsId + '/panel/catalog/',
          import: '/workspace/' + wsId + '/panel/import/',
          analysis: '/workspace/' + wsId + '/panel/analysis/' + scenarioQuery,
          reports: '/workspace/' + wsId + '/panel/reports/',
          basemap: '/workspace/' + wsId + '/panel/basemap/',
        };

        var url = urls[name];
        if (url) {
          htmx.ajax('GET', url, { target: '#left-sidebar-content', swap: 'innerHTML' });
          this.activePanel = name;
        }

        // Expand sidebar if collapsed — set the flag directly rather than
        // calling toggleSidebar(), which would *also* fire its own
        // layer-list load into the same target (content has no child
        // nodes yet, since the fetch above hasn't resolved) and race the
        // tab-specific request above; whichever response lands last wins,
        // so a first click on any non-"layers" tab could silently show
        // the layer list instead.
        this.leftSidebarOpen = true;

        // The Analysis form (checkboxes, JSON config, etc.) and the Data
        // Catalog's multi-column table need more room than the other
        // list-style panels.
        this.sidebarWide = name === 'analysis' || name === 'catalog';
      },

      // ─── Symbology live-preview revert ───────────────────────
      // Live-edit inputs in the symbology editor (color/opacity/column/etc.)
      // mutate the live MapLibre layer directly via 'layer-style-preview'
      // without saving anything — only Save actually persists. If the editor
      // goes away some other way (Cancel, the panel's X, Escape, clicking the
      // map, or navigating to a different panel) that unsaved preview must be
      // reverted back to whatever is actually saved in the database.
      applyLayerStyle: function (layerKey, paint, layout) {
        var mapEl = getMapEl();
        if (!mapEl || !layerKey) return;
        var map = mapEl._map || mapEl['_map'];
        if (!map) return;
        var mapStyle = map.getStyle();
        if (!mapStyle || !mapStyle.layers) return;
        var targetLayer = mapStyle.layers.find(function (l) {
          return l.id.indexOf(layerKey) === 0;
        });
        if (!targetLayer) return;
        if (paint && typeof mapEl.previewLayerStyle === 'function') {
          mapEl.previewLayerStyle(targetLayer.id, paint);
        }
        if (layout) {
          for (var key in layout) {
            try { map.setLayoutProperty(targetLayer.id, key, layout[key]); } catch (e) {}
          }
        }
      },

      revertSymbologyPreview: function () {
        var pk = this.symbologyPreviewLayerPk;
        var layerKey = this.symbologyPreviewLayerKey;
        this.symbologyPreviewLayerPk = null;
        this.symbologyPreviewLayerKey = null;
        if (!pk || !layerKey) return;
        var self = this;
        fetch('/symbology/' + pk + '/preview/')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (style) {
            if (style) self.applyLayerStyle(layerKey, style.paint, style.layout);
          })
          .catch(function () {});
      },

      // Called whenever the right panel's content is (re)established, to
      // start/stop tracking which layer's symbology editor (if any) is now
      // showing — reverting the previous one first if it's being abandoned
      // unsaved.
      trackSymbologyPanel: function () {
        var contentEl = document.getElementById('right-panel-content');
        var editorEl = contentEl && contentEl.querySelector('.symbology-editor-panel[data-layer-pk]');
        var newPk = editorEl ? editorEl.getAttribute('data-layer-pk') : null;

        if (this.symbologyPreviewLayerPk && this.symbologyPreviewLayerPk !== newPk) {
          this.revertSymbologyPreview();
        }
        if (editorEl && newPk) {
          this.symbologyPreviewLayerPk = newPk;
          this.symbologyPreviewLayerKey = editorEl.getAttribute('data-layer-key');
        }
      },

      // ─── Right Panel ───────────────────────────────────────
      openPanel: function (title, contentHtml) {
        var contentEl = document.getElementById('right-panel-content');
        if (!contentEl) return;

        this.rightPanelTitle = title;
        if (contentHtml) {
          contentEl.innerHTML = contentHtml;
        }
        // Panel content can opt into a wider drawer (e.g. a table-heavy form)
        // by including an element with data-wide-panel.
        this.rightPanelWide = !!contentEl.querySelector('[data-wide-panel]');
        this.rightPanelOpen = true;

        this.trackSymbologyPanel();
        this.updateMapPadding();
      },

      closePanel: function () {
        this.revertSymbologyPreview();

        this.rightPanelOpen = false;
        this.rightPanelTitle = '';

        this.updateMapPadding();

        document.body.dispatchEvent(new CustomEvent('panel-closed', { detail: { side: 'right' } }));
      },

      // ─── Bottom Sheet ──────────────────────────────────────
      openSheet: function (title, contentHtml) {
        var contentEl = document.getElementById('bottom-sheet-content');
        if (!contentEl) return;

        this.sheetTitle = title;
        if (contentHtml) {
          contentEl.innerHTML = contentHtml;
        }
        this.bottomSheetOpen = true;

        this.updateMapPadding();
      },

      closeSheet: function () {
        this.bottomSheetOpen = false;
        this.sheetTitle = '';

        this.updateMapPadding();

        document.body.dispatchEvent(new CustomEvent('panel-closed', { detail: { side: 'bottom' } }));
      },

      // ─── Modal ─────────────────────────────────────────────
      openModal: function (contentHtml) {
        if (contentHtml) {
          var contentEl = document.getElementById('modal-content');
          if (contentEl) contentEl.innerHTML = contentHtml;
        }
        this.modalOpen = true;
      },

      closeModal: function () {
        this.modalOpen = false;

        document.body.dispatchEvent(new CustomEvent('panel-closed', { detail: { side: 'modal' } }));
      },

      // ─── Map Integration ───────────────────────────────────
      updateMapPadding: function () {
        var mapEl = getMapEl();
        if (!mapEl) return;

        if (this.rightPanelOpen) {
          mapEl.panelSide = 'right';
          mapEl.panelWidth = 400;
        } else if (this.bottomSheetOpen) {
          mapEl.panelSide = 'bottom';
          mapEl.panelWidth = Math.round(window.innerHeight * 0.4);
        } else {
          mapEl.panelSide = null;
          mapEl.panelWidth = 0;
        }
      },

      // ─── Keyboard ──────────────────────────────────────────
      handleEscape: function () {
        if (this.modalOpen) {
          this.closeModal();
        } else if (this.rightPanelOpen) {
          this.closePanel();
        } else if (this.bottomSheetOpen) {
          this.closeSheet();
        } else if (this.leftSidebarOpen) {
          this.toggleSidebar();
        }
      },
    });

    // Compatibility shim: several server-rendered partials swapped into
    // these panels still call window.__panelManager directly rather than
    // binding to the Alpine store.
    window.__panelManager = {
      openPanel: function (title, contentHtml) { Alpine.store('panels').openPanel(title, contentHtml); },
      closePanel: function () { Alpine.store('panels').closePanel(); },
      openSheet: function (title, contentHtml) { Alpine.store('panels').openSheet(title, contentHtml); },
      closeSheet: function () { Alpine.store('panels').closeSheet(); },
      openModal: function (contentHtml) { Alpine.store('panels').openModal(contentHtml); },
      closeModal: function () { Alpine.store('panels').closeModal(); },
      toggleSidebar: function () { Alpine.store('panels').toggleSidebar(); },
      setSidebarTab: function (name) { Alpine.store('panels').setSidebarTab(name); },
    };
  });

  // ─── ResizeObserver for map element resizing ──────────────
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

  // ─── htmx Event Bridge ────────────────────────────────────
  // htmx 4's htmx:after:settle event carries no request context (just
  // task/newContent/settleTasks), so we bridge on htmx:after:swap instead,
  // which exposes evt.detail.ctx.sourceElement (the element that triggered
  // the request) — see the htmx 4 request-context reference.
  function handleHtmxAfterSettle(evt) {
    var ctx = evt.detail && evt.detail.ctx;
    var sourceEl = ctx && ctx.sourceElement;
    if (!(sourceEl instanceof Element)) return;
    var panelEvent = sourceEl.getAttribute('data-panel-event');
    if (!panelEvent) return;

    var panels = Alpine.store('panels');
    if (panelEvent === 'close-panel') {
      panels.closePanel();
    } else if (panelEvent === 'close-sheet') {
      panels.closeSheet();
    } else if (panelEvent === 'close-modal') {
      panels.closeModal();
    } else if (panelEvent.startsWith('open-panel:')) {
      panels.openPanel(panelEvent.substring('open-panel:'.length));
    } else if (panelEvent.startsWith('open-sheet:')) {
      panels.openSheet(panelEvent.substring('open-sheet:'.length));
    }
  }

  // ─── Window Resize ────────────────────────────────────────
  var resizeTimer = null;

  function handleResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      Alpine.store('panels').updateMapPadding();

      var mapEl = getMapEl();
      if (mapEl && typeof mapEl.resize === 'function') {
        mapEl.resize();
      }
    }, 150);
  }

  // ─── Init ──────────────────────────────────────────────────
  function init() {
    // htmx event bridge
    document.body.addEventListener('htmx:after:swap', handleHtmxAfterSettle);

    // Window resize
    window.addEventListener('resize', handleResize);

    // Map resize observer
    setupMapResizeObserver();

    // ─── Symbology preview (Step 2) ──────────────────────────
    document.body.addEventListener('layer-style-preview', function(evt) {
      var detail = evt.detail;
      if (!detail || !detail.layerKey || !detail.paint) return;
      Alpine.store('panels').applyLayerStyle(detail.layerKey, detail.paint, null);
    });

    // ─── Symbology saved / auto-generated (Steps 3, 5) ──────
    document.body.addEventListener('layer-style-changed', function(evt) {
      var detail = evt.detail;
      if (!detail || !detail.layerKey || !detail.style) return;
      Alpine.store('panels').applyLayerStyle(detail.layerKey, detail.style.paint, detail.style.layout);
    });

    // ─── Layer visibility toggle ────────────────────────────
    document.addEventListener('change', function(evt) {
      var cb = evt.target;
      if (!cb.classList.contains('visibility-toggle')) return;
      var layerKey = cb.getAttribute('data-layer-key');
      if (!layerKey) return;
      var mapEl = getMapEl();
      if (!mapEl) return;
      var map = mapEl._map || mapEl['_map'];
      if (!map) return;
      var style = map.getStyle();
      if (!style || !style.layers) return;
      var targetLayer = style.layers.find(function(l) {
        return l.id.indexOf(layerKey) === 0;
      });
      if (!targetLayer) return;
      mapEl.setLayerVisibility(targetLayer.id, cb.checked);
    });

    // ─── Data table row-click highlight ─────────────────────
    document.addEventListener('click', function(evt) {
      var tr = evt.target.closest('tr[data-feature-id]');
      if (!tr) return;
      var btn = evt.target.closest('.locate-feature-btn');
      if (btn) return; // handled by locate handler below
      var featureId = tr.getAttribute('data-feature-id');
      if (!featureId) return;
      var mapEl = getMapEl();
      if (!mapEl || typeof mapEl.highlightFeatures !== 'function') return;
      mapEl.highlightFeatures([featureId]);
    });

    // ─── Data table locate feature ──────────────────────────
    document.addEventListener('click', function(evt) {
      var btn = evt.target.closest('.locate-feature-btn');
      if (!btn) return;
      evt.stopPropagation();
      var featureId = btn.getAttribute('data-feature-id');
      if (!featureId) return;
      var mapEl = getMapEl();
      if (!mapEl || typeof mapEl.zoomToFeature !== 'function') return;
      mapEl.zoomToFeature(featureId);
    });

    // ─── Filter preview on map ─────────────────────────────
    document.body.addEventListener('filter-preview', function(evt) {
      var detail = evt.detail;
      if (!detail || !detail.layerKey) return;
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
      // Apply or remove filter
      if (detail.filterExpression) {
        try { map.setFilter(targetLayer.id, detail.filterExpression); } catch(e) {}
      } else {
        try { map.setFilter(targetLayer.id, null); } catch(e) {}
      }
    });

    // ─── Toast messages ─────────────────────────────────────
    document.body.addEventListener('show-toast', function(evt) {
      // htmx wraps non-object HX-Trigger payloads as {value: <payload>}
      var detail = evt.detail;
      var msg = detail && typeof detail === 'object' ? detail.value : detail;
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
  }

  // Wait for DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

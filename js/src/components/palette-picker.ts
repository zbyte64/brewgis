import { LitElement, html, nothing } from 'lit'
import { property, state } from 'lit/decorators.js'

/** `[name, colors]` pair, in display order — a palette's swatches for the dropdown. */
export type PaletteOption = [string, string[]]

/**
 * Custom palette picker for the symbology editor: a dropdown that shows every
 * palette's actual swatches up front instead of a bare name.
 *
 * Renders in light DOM (inherits Bootstrap styling) and owns a hidden
 * `<select>` form control, so existing htmx wiring (`hx-post` /
 * `hx-trigger="change"`) placed on this element keeps working unchanged —
 * selecting an option updates that `<select>`'s value and dispatches a
 * bubbling `change` event from it, exactly like a native select would.
 *
 * Callers MUST give this element a stable `id` plus `hx-preserve="true"`.
 * Its light-DOM children (the select/button/menu below) are rendered by
 * Lit, not present in the server-rendered HTML — an `innerMorph` swap's
 * structural diff sees the server's `<palette-picker>` tag as childless and
 * deletes those "extra" live children before Lit ever gets a chance to
 * re-render them back in, permanently emptying the widget. `hx-preserve`
 * makes htmx skip morphing this element entirely and keep the live DOM
 * node (already showing the correct client-selected state), which sidesteps
 * the issue rather than needing to fight the morph.
 */
export class PalettePicker extends LitElement {
  override createRenderRoot() {
    return this
  }

  /** Form field name for the underlying hidden `<select>`. */
  @property({ type: String })
  name = 'palette_name'

  /** Selected palette name, or '' for "Manual" (no palette). */
  @property({ type: String })
  value = ''

  /** `[name, colors[]]` pairs, in display order. */
  @property({ type: Array })
  options: PaletteOption[] = []

  @state()
  private _open = false

  private _onDocumentKeydown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape' && this._open) this._close()
  }

  override connectedCallback(): void {
    super.connectedCallback()
    document.addEventListener('keydown', this._onDocumentKeydown)
  }

  override disconnectedCallback(): void {
    document.removeEventListener('keydown', this._onDocumentKeydown)
    super.disconnectedCallback()
  }

  private _toggleMenu(): void {
    if (this._open) {
      this._close()
    } else {
      this._open = true
    }
  }

  private _close(): void {
    this._open = false
  }

  private _select(name: string): void {
    this.value = name
    this._close()
    const select = this.querySelector('select')
    if (select) {
      select.value = name
      select.dispatchEvent(new Event('change', { bubbles: true }))
    }
  }

  private _renderSwatchRow(colors: string[]) {
    return html`
      <span class="palette-picker-swatch-row">
        ${colors.map(
          (c) => html`<span style="background-color:${c};flex:1;border-radius:2px"></span>`,
        )}
      </span>
    `
  }

  override render() {
    const current = this.options.find(([name]) => name === this.value)
    const currentColors = current ? current[1] : []
    const currentLabel = this.value || 'Manual'

    return html`
      <div class="palette-picker position-relative">
        <select
          name=${this.name}
          class="palette-select visually-hidden"
          tabindex="-1"
          aria-hidden="true"
        >
          <option value="" ?selected=${this.value === ''}>Manual</option>
          ${this.options.map(
            ([name]) =>
              html`<option value=${name} ?selected=${name === this.value}>${name}</option>`,
          )}
        </select>
        <button
          type="button"
          class="form-select form-select-sm palette-picker-toggle d-flex align-items-center gap-2"
          aria-haspopup="listbox"
          aria-expanded=${this._open}
          @click=${() => {
            this._toggleMenu()
          }}
        >
          ${this._renderSwatchRow(currentColors)}
          <span class="palette-picker-current-label flex-grow-1 text-truncate text-start"
            >${currentLabel}</span
          >
        </button>
        <div class="palette-picker-menu ${this._open ? 'is-open' : ''}" role="listbox">
          <div
            class="palette-picker-option ${this.value === '' ? 'is-selected' : ''}"
            role="option"
            @click=${() => {
              this._select('')
            }}
          >
            ${this._renderSwatchRow([])}
            <span>Manual</span>
          </div>
          ${this.options.map(
            ([name, colors]) => html`
              <div
                class="palette-picker-option ${this.value === name ? 'is-selected' : ''}"
                role="option"
                @click=${() => {
                  this._select(name)
                }}
              >
                ${this._renderSwatchRow(colors)}
                <span>${name}</span>
              </div>
            `,
          )}
        </div>
        ${this._open
          ? html`<div
              class="palette-picker-backdrop"
              @click=${() => {
                this._close()
              }}
            ></div>`
          : nothing}
      </div>
    `
  }
}

import { LitElement, html, nothing, type TemplateResult } from 'lit'
import { property, state } from 'lit/decorators.js'
import type {
  ColumnMeta,
  ColumnNode,
  ColumnOperator,
  FilterNode,
  GroupNode,
  SpatialLayerOption,
  SpatialMode,
  SpatialNode,
} from '../types/index.js'

const NUMERIC_OPERATORS: { value: ColumnOperator; label: string }[] = [
  { value: 'eq', label: '=' },
  { value: 'neq', label: '≠' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
  { value: 'is_null', label: 'is empty' },
  { value: 'is_not_null', label: 'is not empty' },
]

const TEXT_OPERATORS: { value: ColumnOperator; label: string }[] = [
  { value: 'eq', label: 'is' },
  { value: 'neq', label: 'is not' },
  { value: 'contains', label: 'contains' },
  { value: 'is_null', label: 'is empty' },
  { value: 'is_not_null', label: 'is not empty' },
]

const NO_VALUE_OPERATORS = new Set<ColumnOperator>(['is_null', 'is_not_null'])

function isGroup(node: FilterNode): node is GroupNode {
  return node != null && node.type === 'group'
}

function isSpatial(node: FilterNode): node is SpatialNode {
  return node?.type === 'spatial'
}

function emptyGroup(): GroupNode {
  return { type: 'group', operator: 'AND', children: [] }
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/**
 * Visual builder for a `LayerFilter.filter_json` expression tree, replacing
 * hand-written JSON. Renders in light DOM so it inherits the page's
 * Bootstrap styling, and mirrors its serialized value into a hidden
 * `<input>` (named via `target-input`) so the existing server-side
 * `filter_json` form field keeps working unchanged.
 */
export class FilterBuilder extends LitElement {
  override createRenderRoot() {
    return this
  }

  /** Available fields to filter on, with a numeric flag driving which operators show. */
  @property({ type: Array })
  columns: ColumnMeta[] = []

  /** Other layers offered as the target of a spatial condition. */
  @property({ type: Array })
  layers: SpatialLayerOption[] = []

  /** Initial expression tree (a LayerFilter's `filter_json`). */
  @property({ type: Object })
  value: FilterNode | null = null

  /** id of the hidden `<input>` this component keeps in sync with. */
  @property({ type: String, attribute: 'target-input' })
  targetInput = ''

  @state()
  private _tree: GroupNode = emptyGroup()

  override connectedCallback(): void {
    super.connectedCallback()
    this._tree = isGroup(this.value as FilterNode)
      ? deepClone(this.value as GroupNode)
      : emptyGroup()
    this._syncHiddenInput()
  }

  private _syncHiddenInput(): void {
    if (!this.targetInput) return
    const input = document.getElementById(this.targetInput) as HTMLInputElement | null
    if (input) input.value = JSON.stringify(this._tree)
  }

  private _setTree(next: GroupNode): void {
    this._tree = next
    this._syncHiddenInput()
    this.dispatchEvent(new CustomEvent('filter-change', { detail: { value: next }, bubbles: true }))
  }

  private _navigateGroup(root: GroupNode, path: number[]): GroupNode {
    let node: GroupNode = root
    for (const idx of path) {
      node = node.children[idx] as GroupNode
    }
    return node
  }

  private _addCondition(path: number[]): void {
    const clone = deepClone(this._tree)
    const firstField = this.columns[0]
    const node: ColumnNode = {
      type: 'column',
      field: firstField?.name ?? '',
      operator: 'eq',
      value: '',
      value_type: firstField?.numeric ? 'number' : 'string',
    }
    this._navigateGroup(clone, path).children.push(node)
    this._setTree(clone)
  }

  private _addGroup(path: number[]): void {
    const clone = deepClone(this._tree)
    this._navigateGroup(clone, path).children.push(emptyGroup())
    this._setTree(clone)
  }

  private _addSpatial(path: number[]): void {
    const clone = deepClone(this._tree)
    const first = this.layers[0]
    const node: SpatialNode = {
      type: 'spatial',
      mode: 'intersects',
      source: first?.value ?? '',
      source_geom: first?.geometry ?? 'geometry',
      buffer_meters: null,
    }
    this._navigateGroup(clone, path).children.push(node)
    this._setTree(clone)
  }

  private _removeChild(path: number[]): void {
    const clone = deepClone(this._tree)
    const parent = this._navigateGroup(clone, path.slice(0, -1))
    parent.children.splice(path[path.length - 1], 1)
    this._setTree(clone)
  }

  private _setGroupOperator(path: number[], operator: 'AND' | 'OR'): void {
    const clone = deepClone(this._tree)
    this._navigateGroup(clone, path).operator = operator
    this._setTree(clone)
  }

  private _updateCondition(path: number[], patch: Partial<ColumnNode>): void {
    const clone = deepClone(this._tree)
    const parent = this._navigateGroup(clone, path.slice(0, -1))
    const node = parent.children[path[path.length - 1]] as ColumnNode
    Object.assign(node, patch)
    this._setTree(clone)
  }

  private _updateSpatial(path: number[], patch: Partial<SpatialNode>): void {
    const clone = deepClone(this._tree)
    const parent = this._navigateGroup(clone, path.slice(0, -1))
    Object.assign(parent.children[path[path.length - 1]], patch)
    this._setTree(clone)
  }

  override render() {
    return html` <div class="filter-builder">${this._renderGroup(this._tree, [], true)}</div> `
  }

  private _renderGroup(group: GroupNode, path: number[], isRoot: boolean): TemplateResult {
    return html`
      <div class=${isRoot ? 'mb-1' : 'border rounded p-2 mb-2 bg-white'} style="font-size: 0.7rem;">
        <div class="d-flex align-items-center gap-1 mb-1">
          <select
            class="form-select form-select-sm w-auto"
            style="font-size: 0.7rem;"
            @change=${(e: Event) =>
              this._setGroupOperator(path, (e.target as HTMLSelectElement).value as 'AND' | 'OR')}
          >
            <option value="AND" ?selected=${group.operator === 'AND'}>Match ALL of</option>
            <option value="OR" ?selected=${group.operator === 'OR'}>Match ANY of</option>
          </select>
          ${!isRoot
            ? html`
                <button
                  type="button"
                  class="btn btn-sm btn-outline-danger py-0 px-1"
                  style="font-size: 0.65rem;"
                  @click=${() => this._removeChild(path)}
                >
                  ✕ remove group
                </button>
              `
            : nothing}
        </div>
        <div class="d-flex flex-column gap-1">
          ${group.children.length === 0
            ? html`<div class="text-muted" style="font-size: 0.65rem;">No conditions yet.</div>`
            : nothing}
          ${group.children.map((child, i) =>
            isGroup(child)
              ? this._renderGroup(child, [...path, i], false)
              : isSpatial(child)
                ? this._renderSpatial(child, [...path, i])
                : this._renderCondition(child, [...path, i]),
          )}
        </div>
        <div class="d-flex gap-1 mt-1">
          <button
            type="button"
            class="btn btn-sm btn-outline-primary py-0 px-1"
            style="font-size: 0.65rem;"
            @click=${() => this._addCondition(path)}
          >
            + Condition
          </button>
          <button
            type="button"
            class="btn btn-sm btn-outline-info py-0 px-1"
            style="font-size: 0.65rem;"
            @click=${() => {
              this._addSpatial(path)
            }}
          >
            + Spatial
          </button>
          <button
            type="button"
            class="btn btn-sm btn-outline-secondary py-0 px-1"
            style="font-size: 0.65rem;"
            @click=${() => this._addGroup(path)}
          >
            + Group
          </button>
        </div>
      </div>
    `
  }

  private _renderCondition(node: ColumnNode, path: number[]): TemplateResult {
    const col = this.columns.find((c) => c.name === node.field)
    const numeric = col ? col.numeric : node.value_type === 'number'
    const operators = numeric ? NUMERIC_OPERATORS : TEXT_OPERATORS
    const needsValue = !NO_VALUE_OPERATORS.has(node.operator)
    const hasColumns = this.columns.length > 0

    return html`
      <div class="d-flex align-items-center gap-1">
        ${hasColumns
          ? html`
              <select
                class="form-select form-select-sm"
                style="font-size: 0.7rem; max-width: 150px;"
                @change=${(e: Event) => {
                  const field = (e.target as HTMLSelectElement).value
                  const nextCol = this.columns.find((c) => c.name === field)
                  this._updateCondition(path, {
                    field,
                    value_type: nextCol?.numeric ? 'number' : 'string',
                  })
                }}
              >
                ${this.columns.map(
                  (c) =>
                    html`<option value=${c.name} ?selected=${c.name === node.field}>
                      ${c.name}
                    </option>`,
                )}
              </select>
            `
          : html`
              <input
                type="text"
                class="form-control form-control-sm"
                style="font-size: 0.7rem; max-width: 150px;"
                placeholder="field"
                .value=${node.field}
                @input=${(e: Event) =>
                  this._updateCondition(path, { field: (e.target as HTMLInputElement).value })}
              />
            `}
        <select
          class="form-select form-select-sm"
          style="font-size: 0.7rem; max-width: 120px;"
          @change=${(e: Event) =>
            this._updateCondition(path, {
              operator: (e.target as HTMLSelectElement).value as ColumnOperator,
            })}
        >
          ${operators.map(
            (op) =>
              html`<option value=${op.value} ?selected=${op.value === node.operator}>
                ${op.label}
              </option>`,
          )}
        </select>
        ${needsValue
          ? html`
              <input
                type=${numeric ? 'number' : 'text'}
                class="form-control form-control-sm"
                style="font-size: 0.7rem;"
                .value=${node.value ?? ''}
                @input=${(e: Event) =>
                  this._updateCondition(path, { value: (e.target as HTMLInputElement).value })}
              />
            `
          : nothing}
        <button
          type="button"
          class="btn btn-sm btn-outline-danger py-0 px-1"
          style="font-size: 0.65rem;"
          @click=${() => this._removeChild(path)}
        >
          ✕
        </button>
      </div>
    `
  }

  private _renderSpatial(node: SpatialNode, path: number[]): TemplateResult {
    const hasLayers = this.layers.length > 0
    // A saved condition can name a layer the current workspace no longer offers
    // (a deleted layer, or a table without a registered geometry). Keep it as a
    // selectable option so opening the editor never silently rewrites it.
    const knownSource = this.layers.some((l) => l.value === node.source)

    return html`
      <div class="d-flex align-items-center gap-1 flex-wrap">
        <select
          class="form-select form-select-sm"
          style="font-size: 0.7rem; max-width: 110px;"
          @change=${(e: Event) => {
            this._updateSpatial(path, {
              mode: (e.target as HTMLSelectElement).value as SpatialMode,
            })
          }}
        >
          <option value="intersects" ?selected=${node.mode === 'intersects'}>intersects</option>
          <option value="excludes" ?selected=${node.mode === 'excludes'}>excludes</option>
        </select>
        ${hasLayers
          ? html`
              <select
                class="form-select form-select-sm"
                style="font-size: 0.7rem; max-width: 180px;"
                @change=${(e: Event) => {
                  const source = (e.target as HTMLSelectElement).value
                  const option = this.layers.find((l) => l.value === source)
                  this._updateSpatial(path, {
                    source,
                    source_geom: option?.geometry ?? 'geometry',
                  })
                }}
              >
                ${knownSource
                  ? nothing
                  : html`<option value=${node.source}>${node.source}</option>`}
                ${this.layers.map(
                  (l) =>
                    html`<option value=${l.value} ?selected=${l.value === node.source}>
                      ${l.label}
                    </option>`,
                )}
              </select>
            `
          : html`
              <input
                type="text"
                class="form-control form-control-sm"
                style="font-size: 0.7rem; max-width: 180px;"
                placeholder="schema.table"
                .value=${node.source}
                @input=${(e: Event) => {
                  this._updateSpatial(path, {
                    source: (e.target as HTMLInputElement).value,
                  })
                }}
              />
            `}
        <input
          type="number"
          class="form-control form-control-sm"
          style="font-size: 0.7rem; max-width: 90px;"
          placeholder="buffer"
          min="0"
          .value=${node.buffer_meters ?? ''}
          @input=${(e: Event) => {
            const raw = (e.target as HTMLInputElement).value
            this._updateSpatial(path, { buffer_meters: raw === '' ? null : Number(raw) })
          }}
        />
        <span class="text-muted" style="font-size: 0.65rem;">m buffer</span>
        <button
          type="button"
          class="btn btn-sm btn-outline-danger py-0 px-1"
          style="font-size: 0.65rem;"
          @click=${() => {
            this._removeChild(path)
          }}
        >
          ✕
        </button>
      </div>
    `
  }
}

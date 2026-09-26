import { describe, it, expect, afterEach } from 'vitest'

import type { FilterBuilder } from '../components/filter-builder.js'
// Import the component to trigger custom element registration
import '../index.js'

/** A spatial condition as it round-trips through the hidden input. */
interface SpatialCondition {
  type: string
  mode: string
  source: string
  source_geom: string
  buffer_meters: number | null
}

interface TreeRoundTrip {
  children: SpatialCondition[]
}

const COLUMNS = [
  { name: 'existing_du', numeric: true },
  { name: 'land_use', numeric: false },
]

const LAYERS = [
  { value: 'public.sac_cnty_base_transit_stops', label: 'Transit Stops', geometry: 'wkb_geometry' },
  { value: 'public.sac_cnty_census_blocks', label: 'Census Blocks', geometry: 'geometry' },
]

async function createElement(opts?: {
  value?: unknown
  columns?: unknown
  layers?: unknown
  targetInput?: string
}): Promise<FilterBuilder> {
  const el = document.createElement('filter-builder')
  if (opts?.columns !== undefined) el.setAttribute('columns', JSON.stringify(opts.columns))
  if (opts?.layers !== undefined) el.setAttribute('layers', JSON.stringify(opts.layers))
  if (opts?.value !== undefined) el.setAttribute('value', JSON.stringify(opts.value))
  if (opts?.targetInput) el.setAttribute('target-input', opts.targetInput)
  document.body.appendChild(el)
  await el.updateComplete
  return el
}

function hiddenInputValue(id: string): unknown {
  const input = document.getElementById(id) as HTMLInputElement
  return JSON.parse(input.value)
}

describe('filter-builder', () => {
  afterEach(() => {
    document.querySelectorAll('filter-builder').forEach((el) => el.remove())
    document.querySelectorAll('input[type="hidden"]').forEach((el) => el.remove())
  })

  it('renders an empty root group with no conditions by default', async () => {
    const el = await createElement({ columns: COLUMNS })
    expect(el.textContent).toContain('No conditions yet.')
    expect(el.querySelectorAll('button').length).toBeGreaterThan(0)
  })

  it('renders an existing filter tree with populated field/operator/value', async () => {
    const value = {
      type: 'group',
      operator: 'AND',
      children: [
        { type: 'column', field: 'existing_du', operator: 'gt', value: '0', value_type: 'number' },
      ],
    }
    const el = await createElement({ columns: COLUMNS, value })
    // First <select> is the group's AND/OR operator; the second is the condition's field.
    const fieldSelect = el.querySelectorAll('select')[1]
    expect(fieldSelect.value).toBe('existing_du')
  })

  it('adding a condition appends a column node and syncs the hidden input', async () => {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_hidden'
    document.body.appendChild(input)

    const el = await createElement({ columns: COLUMNS, targetInput: 'filter_json_hidden' })
    const addConditionBtn = Array.from(el.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('+ Condition'),
    ) as HTMLButtonElement
    addConditionBtn.click()
    await el.updateComplete

    const tree = hiddenInputValue('filter_json_hidden') as any
    expect(tree.children).toHaveLength(1)
    expect(tree.children[0].type).toBe('column')
    expect(tree.children[0].field).toBe('existing_du')
    expect(tree.children[0].value_type).toBe('number')
  })

  it('adding a group appends a nested group node', async () => {
    const el = await createElement({ columns: COLUMNS })
    const addGroupBtn = Array.from(el.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('+ Group'),
    ) as HTMLButtonElement
    addGroupBtn.click()
    await el.updateComplete

    expect(el.textContent).toContain('remove group')
  })

  it('removing a condition removes it from the tree', async () => {
    const value = {
      type: 'group',
      operator: 'AND',
      children: [
        {
          type: 'column',
          field: 'land_use',
          operator: 'eq',
          value: 'residential',
          value_type: 'string',
        },
      ],
    }
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_hidden_2'
    document.body.appendChild(input)

    const el = await createElement({ columns: COLUMNS, value, targetInput: 'filter_json_hidden_2' })
    const removeBtn = el.querySelector('.btn-outline-danger') as HTMLButtonElement
    removeBtn.click()
    await el.updateComplete

    const tree = hiddenInputValue('filter_json_hidden_2') as any
    expect(tree.children).toHaveLength(0)
  })

  it('hides the value input for is_null/is_not_null operators', async () => {
    const value = {
      type: 'group',
      operator: 'AND',
      children: [
        { type: 'column', field: 'land_use', operator: 'is_null', value: '', value_type: 'string' },
      ],
    }
    const el = await createElement({ columns: COLUMNS, value })
    const inputs = el.querySelectorAll('input[type="text"], input[type="number"]')
    expect(inputs.length).toBe(0)
  })

  it('falls back to a free-text field input when no columns are provided', async () => {
    const value = {
      type: 'group',
      operator: 'AND',
      children: [
        { type: 'column', field: 'some_field', operator: 'eq', value: 'x', value_type: 'string' },
      ],
    }
    const el = await createElement({ value })
    const fieldInput = el.querySelector('input[placeholder="field"]') as HTMLInputElement
    expect(fieldInput).toBeTruthy()
    expect(fieldInput.value).toBe('some_field')
  })

  it('adding a spatial condition seeds it from the first layer and syncs the hidden input', async () => {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_spatial'
    document.body.appendChild(input)

    const el = await createElement({
      columns: COLUMNS,
      layers: LAYERS,
      targetInput: 'filter_json_spatial',
    })
    const addSpatial = Array.from(el.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('+ Spatial'),
    ) as HTMLButtonElement
    addSpatial.click()
    await el.updateComplete

    const tree = hiddenInputValue('filter_json_spatial') as TreeRoundTrip
    expect(tree.children).toHaveLength(1)
    expect(tree.children[0]).toEqual({
      type: 'spatial',
      mode: 'intersects',
      source: 'public.sac_cnty_base_transit_stops',
      // The geometry column comes from the chosen layer, not the conventional
      // name — this one is wkb_geometry.
      source_geom: 'wkb_geometry',
      buffer_meters: null,
    })
  })

  it('renders a saved spatial condition and round-trips it unchanged', async () => {
    const value = {
      type: 'group',
      operator: 'AND',
      children: [
        {
          type: 'spatial',
          mode: 'excludes',
          source: 'public.sac_cnty_census_blocks',
          source_geom: 'geometry',
          buffer_meters: 250,
        },
      ],
    }
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_spatial_saved'
    document.body.appendChild(input)

    const el = await createElement({
      columns: COLUMNS,
      layers: LAYERS,
      value,
      targetInput: 'filter_json_spatial_saved',
    })

    // First select is the group's AND/OR, then mode, then the layer.
    const selects = el.querySelectorAll('select')
    expect(selects[1].value).toBe('excludes')
    expect(selects[2].value).toBe('public.sac_cnty_census_blocks')
    expect((el.querySelector('input[type="number"]') as HTMLInputElement).value).toBe('250')

    const tree = hiddenInputValue('filter_json_spatial_saved') as TreeRoundTrip
    expect(tree.children[0]).toEqual(value.children[0])
  })

  it('writes the buffer as a number and back to null when cleared', async () => {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_spatial_buffer'
    document.body.appendChild(input)

    const el = await createElement({
      columns: COLUMNS,
      layers: LAYERS,
      value: {
        type: 'group',
        operator: 'AND',
        children: [
          {
            type: 'spatial',
            mode: 'intersects',
            source: 'public.sac_cnty_census_blocks',
            source_geom: 'geometry',
            buffer_meters: null,
          },
        ],
      },
      targetInput: 'filter_json_spatial_buffer',
    })
    const buffer = el.querySelector('input[type="number"]') as HTMLInputElement

    buffer.value = '500'
    buffer.dispatchEvent(new Event('input', { bubbles: true }))
    await el.updateComplete
    let tree = hiddenInputValue('filter_json_spatial_buffer') as TreeRoundTrip
    expect(tree.children[0].buffer_meters).toBe(500)

    buffer.value = ''
    buffer.dispatchEvent(new Event('input', { bubbles: true }))
    await el.updateComplete
    tree = hiddenInputValue('filter_json_spatial_buffer') as TreeRoundTrip
    expect(tree.children[0].buffer_meters).toBeNull()
  })

  it('changing the source layer updates its geometry column too', async () => {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_spatial_source'
    document.body.appendChild(input)

    const el = await createElement({
      columns: COLUMNS,
      layers: LAYERS,
      value: {
        type: 'group',
        operator: 'AND',
        children: [
          {
            type: 'spatial',
            mode: 'intersects',
            source: 'public.sac_cnty_base_transit_stops',
            source_geom: 'wkb_geometry',
            buffer_meters: null,
          },
        ],
      },
      targetInput: 'filter_json_spatial_source',
    })
    const layerSelect = el.querySelectorAll('select')[2]

    layerSelect.value = 'public.sac_cnty_census_blocks'
    layerSelect.dispatchEvent(new Event('change', { bubbles: true }))
    await el.updateComplete

    const tree = hiddenInputValue('filter_json_spatial_source') as TreeRoundTrip
    expect(tree.children[0].source).toBe('public.sac_cnty_census_blocks')
    expect(tree.children[0].source_geom).toBe('geometry')
  })
})

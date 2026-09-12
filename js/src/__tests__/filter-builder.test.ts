import { describe, it, expect, afterEach } from 'vitest'

// Import the component to trigger custom element registration
import '../index.js'

const COLUMNS = [
  { name: 'existing_du', numeric: true },
  { name: 'land_use', numeric: false },
]

async function createElement(opts?: { value?: unknown; columns?: unknown; targetInput?: string }) {
  const el = document.createElement('filter-builder')
  if (opts?.columns !== undefined) el.setAttribute('columns', JSON.stringify(opts.columns))
  if (opts?.value !== undefined) el.setAttribute('value', JSON.stringify(opts.value))
  if (opts?.targetInput) el.setAttribute('target-input', opts.targetInput)
  document.body.appendChild(el)
  await (el as any).updateComplete
  return el as any
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
    const fieldSelect = el.querySelectorAll('select')[1] as HTMLSelectElement
    expect(fieldSelect.value).toBe('existing_du')
  })

  it('adding a condition appends a column node and syncs the hidden input', async () => {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.id = 'filter_json_hidden'
    document.body.appendChild(input)

    const el = await createElement({ columns: COLUMNS, targetInput: 'filter_json_hidden' })
    const addConditionBtn = (Array.from(el.querySelectorAll('button')) as HTMLButtonElement[]).find(
      (b) => b.textContent?.includes('+ Condition'),
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
    const addGroupBtn = (Array.from(el.querySelectorAll('button')) as HTMLButtonElement[]).find(
      (b) => b.textContent?.includes('+ Group'),
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
})

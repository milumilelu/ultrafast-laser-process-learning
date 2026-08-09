import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { EquipmentProfileForm } from '../EquipmentProfileForm'
import { datasetsApi } from '../../../api/datasets'

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EquipmentProfileForm />
    </QueryClientProvider>,
  )
}

describe('EquipmentProfileForm', () => {
  afterEach(() => vi.restoreAllMocks())

  it('requires a value and field-level verification for every physical input', async () => {
    const create = vi.spyOn(datasetsApi, 'createEquipmentProfile')
    renderForm()
    fireEvent.change(screen.getByRole('textbox', { name: /设备档案名称/ }), {
      target: { value: 'Research fs system A' },
    })
    fireEvent.click(screen.getByRole('button', { name: '创建设备档案' }))

    expect(await screen.findByText('请填写激光波长')).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })

})

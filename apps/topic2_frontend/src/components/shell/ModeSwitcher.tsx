/** ModeSwitcher: Demo（冻结场景，只读）/ Research（完整控制）。 */

import { useModeStore } from '../../stores/mode'
import { StatusBadge } from '../StatusBadge'

export function ModeSwitcher() {
  const mode = useModeStore((state) => state.mode)
  const setMode = useModeStore((state) => state.setMode)

  return (
    <div className="mode-switcher" data-testid="mode-switcher">
      <button
        className={`mode-btn ${mode === 'demo' ? 'active' : ''}`}
        onClick={() => setMode('demo')}
        title="演示模式：绑定 DEMO_SCENARIO_01，科学输入只读，一键运行"
      >
        展示模式
      </button>
      <button
        className={`mode-btn ${mode === 'research' ? 'active' : ''}`}
        onClick={() => setMode('research')}
        title="研究模式：可修改材料/激光/任务/设备/目标，自由运行各阶段"
      >
        研究模式
      </button>
      {mode === 'demo' && <StatusBadge tone="warn">只读</StatusBadge>}
    </div>
  )
}

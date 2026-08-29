import { useCallback, useEffect, useRef, useState } from 'react'
import { GitBranch, Check } from 'lucide-react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import { fetchGitInfo, fetchGitBranches, checkoutBranch } from '../../api/fs'
import { useTranslation } from '../../i18n'
import { useStatusBarConfig } from './useStatusBarConfig'
import { StatusBarItemView } from './StatusBarItem'

interface GitBranchSelectorProps {
  ws: ChatSocket
  workspace: string | null
}

/** git 分支状态栏栏目:受「状态栏栏目开关」控制,非码农工作区不渲染。 */
export function GitBranchSelector({ ws, workspace }: GitBranchSelectorProps) {
  const { config } = useStatusBarConfig()
  if (!config.git) return null
  if (!workspace) return null
  return <GitBranchSelectorInner ws={ws} workspace={workspace} />
}

function GitBranchSelectorInner({ ws, workspace }: { ws: ChatSocket; workspace: string }) {
  const { t } = useTranslation()
  const [branch, setBranch] = useState<string | null>(null)
  const [probeDone, setProbeDone] = useState(false)
  const [open, setOpen] = useState(false)
  const [branches, setBranches] = useState<string[]>([])
  const [loadingBranches, setLoadingBranches] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  // 初始探测一次:非 git 目录则隐藏,不做后台轮询
  useEffect(() => {
    let cancelled = false
    fetchGitInfo(workspace)
      .then(d => {
        if (cancelled) return
        setBranch(d.is_git ? d.branch : null)
        setProbeDone(true)
      })
      .catch(() => {
        if (!cancelled) { setBranch(null); setProbeDone(true) }
      })
    return () => { cancelled = true }
  }, [workspace])

  // 订阅后端广播的 git_branch 事件,切换分支后实时刷新(无需轮询)
  useEffect(() => {
    const unsub = ws.subscribe(msg => {
      const gb = msg.git_branch
      if (gb && gb.workspace === workspace) setBranch(gb.branch)
    })
    return unsub
  }, [ws, workspace])

  const openPanel = useCallback(() => {
    setOpen(true)
    setLoadingBranches(true)
    setError(null)
    fetchGitBranches(workspace)
      .then(d => setBranches(d.branches))
      .catch(() => setError(t('git.loadFailed')))
      .finally(() => setLoadingBranches(false))
  }, [workspace, t])

  // 面板打开期间:Esc 或外部点击关闭
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  // 探测完成前不渲染,避免闪错;探测到非 git 则隐藏
  if (!probeDone) return null
  if (!branch) return null

  const handleSwitch = async (target: string) => {
    if (switching) return
    setSwitching(true)
    setError(null)
    try {
      const d = await checkoutBranch(workspace, target)
      setBranch(d.branch)
      setOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('git.switchFailed'))
    } finally {
      setSwitching(false)
    }
  }

  return (
    <div className="role-float" ref={wrapRef} data-testid="git-branch-selector">
      <StatusBarItemView
        icon={<GitBranch size={13} aria-hidden="true" />}
        label={branch}
        state="ok"
        title={t('statusbar.gitTitle').replace('{branch}', branch)}
        onClick={() => (open ? setOpen(false) : openPanel())}
      />
      {open && (
        <div className="role-float__panel role-float__panel--right" role="listbox" data-testid="git-branch-menu">
          <div className="role-float__heading">{t('git.chooseBranch')}</div>
          {loadingBranches && <div className="role-float__empty">{t('common.loading')}</div>}
          {error && (
            <div className="role-float__empty" role="alert" data-testid="git-branch-error">
              {error}
            </div>
          )}
          {!loadingBranches && !error && branches.map(name => {
            const selected = name === branch
            return (
              <button
                key={name}
                type="button"
                role="option"
                aria-selected={selected}
                className={`role-float__option${selected ? ' is-selected' : ''}`}
                data-testid={`git-branch-option-${name}`}
                disabled={switching || selected}
                onClick={() => handleSwitch(name)}
              >
                <span className="role-float__option-body">
                  <span className="role-float__name">{name}</span>
                </span>
                {selected && <Check size={14} className="role-float__check" />}
              </button>
            )
          })}
          {!loadingBranches && !error && branches.length === 0 && (
            <div className="role-float__empty">{t('git.noBranches')}</div>
          )}
        </div>
      )}
    </div>
  )
}

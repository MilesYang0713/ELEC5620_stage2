import { useEffect, useState, type FormEvent } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, BarChart3, Bell, Check, ChevronDown, CircleHelp, Clock3, Database, LayoutDashboard, LogOut, Menu, MessageSquareText, Package, Play, ShieldCheck, ShoppingBag, Sparkles, X } from 'lucide-react'

type Agent = { agent: string; status: string; summary: string; evidence: string[]; limitations: string[] }
type Recommendation = { id: string; title: string; priority: string; action: string; evidence: string[]; confidence: string; high_risk: boolean; status: string; approval_note: string }
type Product = { id: string; name: string; category: string; price: number; stock: number; units_sold_7d: number; units_sold_prev_7d: number; units_sold_14d?: number; revenue_7d?: number; revenue_prev_7d?: number; revenue_14d?: number }
type FeedbackRecord = { id: string; product_id: string; category: string; content: string; submitted_at: string }
type Run = { id: string; question: string; workflow: string; status: string; data_mode: string; created_at: string; agents: Agent[]; recommendations: Recommendation[]; limitations: string[]; scope?: { product_id?: string; product_name?: string } }
type ProductInsight = { product_id: string; weekly_change_percent: number; estimated_cover_days: number | null; latest_week_revenue: number; risk: string }
type FeedbackClassification = { id: string; themes: string[]; sentiment: string; priority: string }
type InventoryMovement = { id: string; product_id: string; product_name: string; movement_type: string; quantity: number; note: string; occurred_at: string; updated_stock?: number }
type Dashboard = { data_mode: string; business_as_of_date?: string; products: Product[]; feedback_count: number; feedback: FeedbackRecord[]; runs: Run[]; audit: { id: string; event: string; summary: string; created_at: string; feedback_id?: string }[]; movements: InventoryMovement[]; insights?: { products: ProductInsight[]; feedback: { theme_counts: Record<string, number>; sentiment_counts: Record<string, number>; record_count: number; classifications: FeedbackClassification[] } } }
type SalesPoint = { date: string; quantity: number; revenue: number }
type ProductTrend = { product_id: string; days: number; sales: SalesPoint[]; movements: InventoryMovement[]; sales_source: 'recorded' | 'illustrative' }
type TrendMetric = 'quantity' | 'revenue'
type WorkspaceSection = 'overview' | 'product-trends' | 'agent-runs' | 'approvals' | 'customer-voice'
type OwnerSession = { email: string; name: string; role: string }
type WorkflowChoice = { key: string; label: string }
type AnalysisActivity = { phase: 'running' | 'completed' | 'partial' | 'failed' | 'clarification'; workflow: string; startedAt: number; duration: number; message?: string; choices?: WorkflowChoice[] }
type DirectAnswer = { kind: 'answer'; title: string; answer: string; evidence: string[]; period_start: string; period_end: string; data_source: string }
type AssistantReply = { kind: 'analysis'; run: Run } | DirectAnswer | { kind: 'clarification'; message: string; choices: WorkflowChoice[] }

const scenarios = [
  { key: 'sales_decline', label: 'Sales decline', prompt: 'Why are Harbour Blend Coffee sales falling, and what should I do?' },
  { key: 'overstock', label: 'Overstock', prompt: 'How should I clear slow-moving Coastal Oat Biscuits stock?' },
  { key: 'demand_spike', label: 'Demand spike', prompt: 'Wattle Hand Balm demand suddenly spiked. How do I avoid a stock-out?' },
  { key: 'feedback_analysis', label: 'Customer feedback', prompt: 'Analyse customer feedback and suggest improvements.' },
]

const money = (amount: number) => new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(amount)
const time = (value: string) => new Date(value).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' })
const workflowChoices = [
  { key: 'sales_decline', label: 'Sales decline' },
  { key: 'overstock', label: 'Overstock' },
  { key: 'demand_spike', label: 'Demand spike' },
  { key: 'feedback_analysis', label: 'Customer feedback' },
]

function conciseSummary(value: string): string {
  const clean = value.trim().replace(/\s+/g, ' ')
  const firstTwoSentences = clean.split(/(?<=[.!?。！？])\s+/).slice(0, 2).join(' ')
  if (firstTwoSentences.length <= 280) return firstTwoSentences
  const shortened = firstTwoSentences.slice(0, 277)
  return `${shortened.slice(0, shortened.lastIndexOf(' ')).trimEnd()}…`
}

function focusProduct(products: Product[]): Product | undefined {
  if (!products.length) return undefined
  const decline = (product: Product) => product.units_sold_prev_7d > 0
    ? Math.max(0, (product.units_sold_prev_7d - product.units_sold_7d) / product.units_sold_prev_7d)
    : 0
  const lowStock = products.filter((product) => product.stock < 15)
    .sort((a, b) => a.stock - b.stock || decline(b) - decline(a))
  if (lowStock.length) return lowStock[0]
  const declining = products.filter((product) => decline(product) > 0)
    .sort((a, b) => decline(b) - decline(a))
  return declining[0] ?? products[0]
}

async function readJson<T>(response: Response): Promise<T> {
  const raw = await response.text()
  let body: unknown
  try { body = JSON.parse(raw) }
  catch {
    if (!response.ok) throw new Error(`API gateway returned HTTP ${response.status} without JSON. The model request may have timed out; check Docker logs before retrying.`)
    throw new Error(`API returned a non-JSON response (HTTP ${response.status}). Check that the frontend and API containers were rebuilt together.`)
  }
  if (!response.ok) {
    const detail = typeof body === 'object' && body !== null && 'detail' in body ? String((body as { detail: unknown }).detail) : 'API request failed.'
    throw new Error(detail)
  }
  return body as T
}

export default function App() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [question, setQuestion] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const [directAnswer, setDirectAnswer] = useState<DirectAnswer | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const [historyRuns, setHistoryRuns] = useState<Run[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [analysisActivity, setAnalysisActivity] = useState<AnalysisActivity | null>(null)
  const [analysisElapsed, setAnalysisElapsed] = useState(0)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [simulateFailure, setSimulateFailure] = useState(false)
  const [activeSection, setActiveSection] = useState<WorkspaceSection>('overview')
  const [hoveredSection, setHoveredSection] = useState<WorkspaceSection | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [authReady, setAuthReady] = useState(false)
  const [authRequired, setAuthRequired] = useState(false)
  const [session, setSession] = useState<OwnerSession | null>(null)
  const [authError, setAuthError] = useState('')
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [analysisProductId, setAnalysisProductId] = useState('')
  const [feedbackProductFilter, setFeedbackProductFilter] = useState('all')
  const [feedbackCategoryFilter, setFeedbackCategoryFilter] = useState('all')
  const [feedbackOnlyEscalated, setFeedbackOnlyEscalated] = useState(false)
  const [movementOpen, setMovementOpen] = useState(false)
  const [movementProductId, setMovementProductId] = useState('')
  const [movementType, setMovementType] = useState<'receipt' | 'write_off'>('receipt')
  const [movementQuantity, setMovementQuantity] = useState('')
  const [movementNote, setMovementNote] = useState('')
  const [trendProductId, setTrendProductId] = useState('')
  const [trendDays, setTrendDays] = useState<7 | 14>(14)
  const [trendMetric, setTrendMetric] = useState<TrendMetric>('quantity')
  const [productTrend, setProductTrend] = useState<ProductTrend | null>(null)
  const [trendLoading, setTrendLoading] = useState(false)
  const [trendError, setTrendError] = useState('')
  const [rejectingRecommendation, setRejectingRecommendation] = useState<Recommendation | null>(null)
  const [rejectionNote, setRejectionNote] = useState('')
  const [decisionBusy, setDecisionBusy] = useState(false)

  function openSection(section: WorkspaceSection) {
    setActiveSection(section)
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>('.page-content')?.scrollTo({ top: 0, behavior: 'smooth' }))
  }

  function ownerFetch(input: RequestInfo | URL, init?: RequestInit) {
    const headers = new Headers(init?.headers)
    const token = window.localStorage.getItem('soloretail_owner_token')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(input, { ...init, headers })
  }

  useEffect(() => {
    const available = data?.products ?? []
    if (!available.length) return
    setTrendProductId((current) => available.some((product) => product.id === current)
      ? current
      : focusProduct(available)?.id ?? available[0].id)
  }, [data?.products])

  useEffect(() => {
    if (window.location.pathname === '/customer' || !data || !trendProductId) return
    let ignore = false
    const requestedDays = activeSection === 'overview' ? 7 : trendDays
    async function loadTrend() {
      setTrendLoading(true)
      setTrendError('')
      try {
        const response = await ownerFetch(`/api/products/${encodeURIComponent(trendProductId)}/trend?days=${requestedDays}`)
        const result = await readJson<ProductTrend>(response)
        if (!ignore) setProductTrend(result)
      } catch (e) {
        if (!ignore) {
          setProductTrend(null)
          setTrendError(e instanceof Error ? e.message : 'Could not load product trends.')
        }
      } finally {
        if (!ignore) setTrendLoading(false)
      }
    }
    void loadTrend()
    return () => { ignore = true }
  }, [activeSection, data?.data_mode, trendDays, trendProductId])

  useEffect(() => {
    if (analysisActivity?.phase !== 'running') return
    const timer = window.setInterval(() => setAnalysisElapsed(Math.floor((Date.now() - analysisActivity.startedAt) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [analysisActivity?.phase, analysisActivity?.startedAt])

  async function refresh() {
    try {
      const [dashboardResponse, historyResponse] = await Promise.all([ownerFetch('/api/dashboard'), ownerFetch('/api/analyses')])
      const dashboard = await readJson<Dashboard>(dashboardResponse)
      setData(dashboard)
      setHistoryRuns(await readJson<Run[]>(historyResponse))
      setError('')
    }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not reach the API. Start the backend or Docker Compose, then refresh.') }
  }
  useEffect(() => {
    if (window.location.pathname === '/customer') return
    void (async () => {
      try {
        const config = await readJson<{ authentication_required: boolean }>(await fetch('/api/auth/config'))
        setAuthRequired(config.authentication_required)
        if (config.authentication_required) {
          const response = await ownerFetch('/api/auth/session')
          if (response.status === 401) {
            window.localStorage.removeItem('soloretail_owner_token')
            setAuthError('Please sign in to continue.')
          } else {
            const body = await readJson<{ session: OwnerSession }>(response)
            setSession(body.session)
          }
        } else {
          setSession({ email: 'local-owner@prototype.invalid', name: 'Jordan Mitchell', role: 'Store owner' })
        }
        await refresh()
      } catch (e) {
        const message = e instanceof Error ? e.message : 'Could not initialise the owner session.'
        if (message.includes('HTTP 401')) setAuthError('Please sign in to continue.')
        else setError(message)
      } finally { setAuthReady(true) }
    })()
  }, [])

  if (window.location.pathname === '/customer') return <CustomerFeedbackPage />

  async function analyze(prompt = question, workflow?: string) {
    if (busy) return
    if (prompt.trim().length < 5) { setError('Enter a little more detail so the Manager Agent can scope the analysis.'); return }
    const activity: AnalysisActivity = { phase: 'running', workflow: workflow ?? 'custom analysis', startedAt: Date.now(), duration: 0 }
    setAnalysisActivity(activity); setAnalysisElapsed(0); setDirectAnswer(null)
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await ownerFetch('/api/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: prompt, workflow, product_id: analysisProductId || null, simulate_failures: simulateFailure ? ['Marketing Agent'] : [] }) })
      const body = await readJson<AssistantReply>(response)
      if (body.kind === 'answer') {
        setDirectAnswer(body); setRun(null); setQuestion(prompt); setSelectedAgent(null); setAnalysisActivity(null)
        openSection('agent-runs')
        await refresh()
        return
      }
      if (body.kind === 'clarification') {
        setQuestion(prompt)
        setAnalysisActivity({ ...activity, phase: 'clarification', workflow: 'question routing', duration: Math.floor((Date.now() - activity.startedAt) / 1000), message: body.message, choices: body.choices })
        return
      }
      setDirectAnswer(null)
      const analysisRun = body.run
      setRun(analysisRun); setQuestion(prompt); setSelectedAgent(null)
      setAnalysisActivity({ ...activity, phase: analysisRun.status === 'partial' ? 'partial' : analysisRun.status === 'completed' ? 'completed' : 'failed', duration: Math.floor((Date.now() - activity.startedAt) / 1000) })
      openSection('agent-runs')
      await refresh()
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Analysis failed.'
      setAnalysisActivity({ ...activity, phase: 'failed', duration: Math.floor((Date.now() - activity.startedAt) / 1000), message })
    }
    finally { setBusy(false) }
  }

  async function decide(rec: Recommendation, decision: 'approve' | 'reject', note = '') {
    setDecisionBusy(true)
    setError('')
    try {
      const response = await ownerFetch(`/api/recommendations/${rec.id}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note: note.trim() }) })
      const body = await readJson<{ recommendation: Recommendation; message: string }>(response)
      setRun((current) => current ? { ...current, recommendations: current.recommendations.map((item) => item.id === rec.id ? body.recommendation : item) } : current)
      setNotice(body.message); await refresh()
      if (decision === 'reject') {
        setRejectingRecommendation(null)
        setRejectionNote('')
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Approval failed.') }
    finally { setDecisionBusy(false) }
  }

  function openRejectForm(rec: Recommendation) {
    setError('')
    setRejectionNote('')
    setRejectingRecommendation(rec)
  }

  function submitRejection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!rejectingRecommendation) return
    const note = rejectionNote.trim()
    void decide(rejectingRecommendation, 'reject', note)
  }

  async function escalateFeedback(feedbackId: string) {
    try {
      const response = await ownerFetch(`/api/feedback/${feedbackId}/escalate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note: '' }) })
      const body = await readJson<{ message: string }>(response)
      setNotice(body.message); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not mark feedback for review.') }
  }

  async function recordMovement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const productId = movementProductId || products[0]?.id
    const quantity = Number(movementQuantity)
    if (!productId || !Number.isInteger(quantity) || quantity < 1) { setError('Choose a product and enter a whole-number quantity of at least 1.'); return }
    try {
      const response = await ownerFetch('/api/inventory/movements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ product_id: productId, movement_type: movementType, quantity, note: movementNote }) })
      const body = await readJson<{ message: string }>(response)
      setNotice(body.message); setMovementQuantity(''); setMovementNote(''); setMovementOpen(false); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not record the inventory movement.') }
  }

  const products = data?.products ?? []
  const selectedTrendProduct = products.find((product) => product.id === trendProductId) ?? focusProduct(products)
  const requestedTrendDays = activeSection === 'overview' ? 7 : trendDays
  const trendMatchesSelection = productTrend?.product_id === selectedTrendProduct?.id && productTrend?.days === requestedTrendDays
  const productInsights = new Map((data?.insights?.products ?? []).map((item) => [item.product_id, item]))
  const feedbackClassifications = new Map((data?.insights?.feedback.classifications ?? []).map((item) => [item.id, item]))
  const escalatedFeedback = new Set((data?.audit ?? []).filter((entry) => entry.event === 'feedback_escalated' && entry.feedback_id).map((entry) => entry.feedback_id))
  const storedRuns = historyRuns ?? data?.runs ?? []
  const allRuns = Array.from(new Map([...(data?.runs ?? []), ...storedRuns, run].filter((item): item is Run => Boolean(item)).map((item) => [item.id, item])).values())
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  const currentRun = directAnswer ? null : run ?? allRuns[0] ?? null
  const activeRecommendation = currentRun?.recommendations[0]
  const selectedAgentResult = currentRun?.agents.find((agent) => agent.agent === selectedAgent) ?? null
  const selectedAgentUnavailable = selectedAgentResult?.status === 'failed'
  const summaryText = selectedAgentResult
    ? selectedAgentUnavailable ? 'This agent could not produce a result for this run.' : conciseSummary(selectedAgentResult.summary)
    : activeRecommendation?.action ?? ''
  const summaryEvidence = selectedAgentResult ? selectedAgentResult.evidence.slice(0, 2) : activeRecommendation?.evidence.slice(0, 2) ?? []
  const currentUnits = products.reduce((sum, p) => sum + p.units_sold_7d, 0)
  const previousUnits = products.reduce((sum, p) => sum + p.units_sold_prev_7d, 0)
  const unitChange = previousUnits ? Math.round((currentUnits - previousUnits) / previousUnits * 100) : 0
  const currentRevenue = products.reduce((sum, p) => sum + (p.revenue_7d ?? p.units_sold_7d * p.price), 0)
  const previousRevenue = products.reduce((sum, p) => sum + (p.revenue_prev_7d ?? p.units_sold_prev_7d * p.price), 0)
  const revenueChange = previousRevenue ? Math.round((currentRevenue - previousRevenue) / previousRevenue * 100) : 0
  const approvals = allRuns.flatMap((item) => item.recommendations.filter((recommendation) => recommendation.high_risk && recommendation.status === 'pending_approval').map((recommendation) => ({ run: item, recommendation })))
  const supabaseMode = data?.data_mode === 'supabase' || data?.data_mode === 'supabase_llm'
  const llmMode = data?.data_mode === 'llm' || data?.data_mode === 'supabase_llm'
  const dataSourceTitle = supabaseMode ? (llmMode ? 'Supabase data · Qwen analysis' : 'Supabase database is active') : (llmMode ? 'Qwen analysis is active' : 'Demo data is active')
  const reportDate = data?.business_as_of_date ?? '2026-11-04'
  const dataSourceDescription = `${supabaseMode ? 'Products, sales and feedback are loaded from your Supabase project. ' : ''}Illustrative reporting date: ${new Date(`${reportDate}T12:00:00`).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}. Figures are sample records, not live store data.`
  const dataSourceTag = supabaseMode ? (llmMode ? 'SUPABASE · QWEN' : 'SUPABASE') : (llmMode ? 'LLM · DEMO DATA' : 'LOCAL DEMO')
  const sectionTitle: Record<WorkspaceSection, string> = { overview: 'Overview', 'product-trends': 'Product trends', 'agent-runs': 'Agent runs', approvals: 'Approvals', 'customer-voice': 'Customer voice' }
  const visibleFeedback = (data?.feedback ?? []).filter((item) => (feedbackProductFilter === 'all' || item.product_id === feedbackProductFilter) && (feedbackCategoryFilter === 'all' || item.category === feedbackCategoryFilter) && (!feedbackOnlyEscalated || escalatedFeedback.has(item.id)))

  async function signIn(email: string, password: string) {
    setAuthError('')
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) })
      const body = await readJson<{ token: string; session: OwnerSession }>(response)
      window.localStorage.setItem('soloretail_owner_token', body.token)
      setSession(body.session)
      await refresh()
    } catch (e) { setAuthError(e instanceof Error ? e.message : 'Sign-in failed.') }
  }

  async function signOut() {
    try { await ownerFetch('/api/auth/logout', { method: 'POST' }) }
    finally {
      window.localStorage.removeItem('soloretail_owner_token')
      setSession(null); setData(null); setRun(null); setAccountMenuOpen(false)
    }
  }

  if (window.location.pathname === '/customer') return <CustomerFeedbackPage />
  if (!authReady) return <AuthLoading />
  if (authRequired && !session) return <LoginPage error={authError} onSubmit={signIn} />

  return <div className={`app-shell ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
    <aside className={`sidebar ${hoveredSection ? 'sidebar-previewing' : ''}`}>
      <div className="brand"><div className="brand-mark"><ShoppingBag size={19} /></div><div><b>SoloRetail</b><span>AI OPERATIONS</span></div></div>
      <div className="nav-label">WORKSPACE</div>
      <nav onMouseLeave={() => setHoveredSection(null)}>
        <button className={`nav-item ${activeSection === 'overview' ? 'active' : ''} ${hoveredSection === 'overview' ? 'hovered' : ''}`} onMouseEnter={() => setHoveredSection('overview')} onClick={() => openSection('overview')}><LayoutDashboard size={17}/> Overview</button>
        <button className={`nav-item ${activeSection === 'product-trends' ? 'active' : ''} ${hoveredSection === 'product-trends' ? 'hovered' : ''}`} onMouseEnter={() => setHoveredSection('product-trends')} onClick={() => openSection('product-trends')}><BarChart3 size={17}/> Product trends</button>
        <button className={`nav-item ${activeSection === 'agent-runs' ? 'active' : ''} ${hoveredSection === 'agent-runs' ? 'hovered' : ''}`} onMouseEnter={() => setHoveredSection('agent-runs')} onClick={() => openSection('agent-runs')}><Activity size={17}/> Agent runs <span className="nav-count">{allRuns.length}</span></button>
        <button className={`nav-item ${activeSection === 'approvals' ? 'active' : ''} ${hoveredSection === 'approvals' ? 'hovered' : ''}`} onMouseEnter={() => setHoveredSection('approvals')} onClick={() => openSection('approvals')}><ShieldCheck size={17}/> Approvals {approvals.length > 0 && <i className="nav-dot"/>}</button>
        <button className={`nav-item ${activeSection === 'customer-voice' ? 'active' : ''} ${hoveredSection === 'customer-voice' ? 'hovered' : ''}`} onMouseEnter={() => setHoveredSection('customer-voice')} onClick={() => openSection('customer-voice')}><MessageSquareText size={17}/> Customer voice</button>
      </nav>
      <div className="sidebar-bottom"><button className="help-card" onClick={()=>setNotice('Demo guide: choose a workflow, inspect evidence and limitations, then approve or reject only high-risk recommendations.')}><CircleHelp size={17}/><div><b>Need a hand?</b><span>View the demo guide</span></div></button><div className="profile-wrap"><button className="profile" onClick={() => setAccountMenuOpen((open) => !open)} aria-expanded={accountMenuOpen}><div className="profile-avatar">JM</div><div><b>{session?.name ?? 'Jordan Mitchell'}</b><span>{session?.role ?? 'Store owner'}</span></div><ChevronDown size={14}/></button>{accountMenuOpen && <div className="account-menu"><b>{session?.name ?? 'Jordan Mitchell'}</b><span>{authRequired ? session?.email : 'Local prototype access'}</span>{authRequired ? <button onClick={() => void signOut()}><LogOut size={14}/> Sign out</button> : <small>Set `AUTH_REQUIRED=true` to enable owner sign-in.</small>}</div>}</div></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="sidebar-toggle" aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'} title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'} onClick={() => setSidebarOpen((open) => !open)}><Menu size={18}/></button><div className="breadcrumbs">Workspace <span>/</span> <b>{sectionTitle[activeSection]}</b></div></div><div className="top-actions"><span className="live-pill"><i/> {supabaseMode ? 'Supabase environment' : 'Demo environment'}</span><div className="store-switch top-store-switch"><div className="store-avatar">H</div><div><b>Harbour & Co.</b><span>Independent retailer</span></div></div><button className="icon-button" aria-label="Notifications" onClick={()=>setNotice(approvals.length ? `${approvals.length} high-risk recommendation${approvals.length === 1 ? '' : 's'} awaiting owner review.` : 'No high-risk recommendations are awaiting owner review.')}><Bell size={17}/>{approvals.length > 0 && <i/>}</button><div className="top-avatar">JM</div></div></header>
      <div className={`page-content module-${activeSection}`}>
        {error && <div className="alert error"><X size={16}/>{error}<button onClick={() => void refresh()}>Refresh data</button></div>}
        {notice && <div className="alert success"><Check size={16}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss">×</button></div>}
        {analysisActivity && <div className={`analysis-activity ${analysisActivity.phase}`} role="status">
          <span className="analysis-activity-icon">{analysisActivity.phase === 'completed' ? <Check size={16}/> : analysisActivity.phase === 'failed' ? <X size={16}/> : <Clock3 size={16}/>}</span>
          <div><b>{analysisActivity.phase === 'running' ? 'Analysis in progress' : analysisActivity.phase === 'completed' ? 'Analysis completed' : analysisActivity.phase === 'partial' ? 'Partial analysis completed' : analysisActivity.phase === 'clarification' ? 'Choose an analysis focus' : 'Analysis failed'}</b>
            <span>{analysisActivity.workflow.replace(/_/g, ' ')} · {analysisActivity.phase === 'running' ? 'Waiting for the API response' : `Finished in ${analysisActivity.duration}s`}</span>
            <p>{analysisActivity.phase === 'running' ? 'The server is processing the specialist and Manager requests. Results and agent statuses appear after the API responds; keep this tab open.' : analysisActivity.message ?? (analysisActivity.phase === 'partial' ? 'Some agents were unavailable. Check the result and limitations before using the recommendation.' : analysisActivity.phase === 'failed' ? 'The server returned a failed analysis. Check the result and API logs.' : analysisActivity.phase === 'clarification' ? 'Your question is still here. Choose the closest workflow and we will use it as the analysis focus.' : 'Open the result to review evidence, recommendations and approval controls.')}</p>
            {analysisActivity.phase === 'clarification' && <div className="workflow-clarification"><span>Choose a workflow to continue:</span><div>{(analysisActivity.choices ?? workflowChoices).map((choice) => <button key={choice.key} onClick={() => { setSelectedAgent(null); void analyze(question, choice.key) }}>{choice.label}</button>)}</div></div>}
          </div>
          {analysisActivity.phase === 'running' ? <span className="analysis-timer" aria-label="Elapsed time">{analysisElapsed}s elapsed</span> : run && analysisActivity.phase !== 'failed' && analysisActivity.phase !== 'clarification' ? <button className="text-button" onClick={() => openSection('agent-runs')}>View result <ArrowUpRight size={13}/></button> : null}
        </div>}
        <div className="workspace-module overview-module">
        <div className="page-heading" id="overview"><div><div className="eyebrow">BUSINESS OVERVIEW <span>·</span> SYDNEY, AU</div><h1>Store performance</h1></div><button className="date-filter" onClick={()=>setNotice('All sales comparisons use the latest 7 days against the preceding 7 days.')}><Clock3 size={15}/> Last 7 days <ChevronDown size={14}/></button></div>
        <div className="demo-banner"><div className="demo-icon"><Database size={16}/></div><div><b>{dataSourceTitle}</b><span>{dataSourceDescription}</span></div><span className="demo-tag">{dataSourceTag}</span></div>
        <section className="metric-grid">
          <Metric title="Sales · last 7 days" value={money(currentRevenue)} change={`${Math.abs(revenueChange)}%`} down={revenueChange < 0} note="vs previous 7 days" icon="↘" tone="sage"/>
          <Metric title="Units sold" value={String(currentUnits)} change={`${Math.abs(unitChange)}%`} down={unitChange < 0} note="vs previous 7 days" icon="▤" tone="lavender"/>
          <Metric title="Products to watch" value={String(products.filter(p=>p.stock<15 || p.units_sold_7d<p.units_sold_prev_7d).length)} change="review evidence" note="low stock or declining sales" icon="!" tone="peach"/>
          <Metric title="Customer feedback" value={String(data?.feedback_count ?? 0)} change="record-grounded" note="available for analysis" icon="♡" tone="blue"/>
        </section>

        <div className="content-grid">
          <section className="panel analysis-panel">
            <div className="panel-heading"><div><div className="section-kicker"><Sparkles size={14}/> AI BUSINESS ASSISTANT</div><h2>What would you like to work on?</h2><p>Ask a question or start with a common workflow.</p></div><span className="manager-badge"><i/> Manager ready</span></div>
            <div className="composer"><textarea value={question} onChange={(e)=>setQuestion(e.target.value)} onKeyDown={(e)=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();void analyze()}}} placeholder="e.g. Why are my coffee sales slowing down?" rows={2}/><div className="scope-row"><label>Focus product <select value={analysisProductId} onChange={(event)=>setAnalysisProductId(event.target.value)}><option value="">All available products</option>{products.map((product)=><option value={product.id} key={product.id}>{product.name}</option>)}</select></label><span>Optional scope narrows the evidence used in this run.</span></div><div className="composer-bottom"><label className="failure-toggle"><input type="checkbox" checked={simulateFailure} onChange={(event)=>setSimulateFailure(event.target.checked)} /> Demonstrate a missing Marketing Agent result</label><button className="primary-button" disabled={busy} onClick={()=>void analyze()}><Play size={14} fill="currentColor"/>{busy?'Analysing…':'Run analysis'}</button></div></div>
            <div className="scenario-row">{scenarios.map((s)=><button key={s.key} className="scenario-chip" disabled={busy} onClick={()=>{setQuestion(s.prompt);setAnalysisProductId('');setDirectAnswer(null);setAnalysisActivity(null)}} title="Fill the question; press Run analysis when ready"><span className={`scenario-dot ${s.key}`}/>{s.label}<ArrowUpRight size={12}/></button>)}</div>
          </section>
          <section className="panel watch-panel"><div className="panel-title-row"><div><div className="section-kicker">STORE PULSE</div><h2>Needs a closer look</h2></div><a className="text-button" href="#inventory">View all <ArrowUpRight size={13}/></a></div>
            {products.filter(p=>p.stock<15 || p.units_sold_7d<p.units_sold_prev_7d).map(p=>{const insight=productInsights.get(p.id);return <div className="watch-item" key={p.id}><div className="product-icon">{p.category==='Wellness'?'✳':'◉'}</div><div className="watch-info"><b>{p.name}</b><span>{insight?.estimated_cover_days != null ? `${insight.estimated_cover_days} days cover · ${insight.risk.replace(/_/g,' ')}` : `${p.units_sold_7d} sold this week`}</span></div><span className={`trend ${p.units_sold_7d<p.units_sold_prev_7d?'negative':'positive'}`}>{p.units_sold_7d<p.units_sold_prev_7d?<ArrowDownRight size={14}/>:<ArrowUpRight size={14}/>} {insight ? `${insight.weekly_change_percent > 0 ? '+' : ''}${insight.weekly_change_percent}%` : p.units_sold_7d-p.units_sold_prev_7d}</span></div>})}
            {!products.length && <div className="empty-small">Store metrics will appear when the API is running.</div>}
          </section>
        </div>

        <section className="panel product-trend-preview">
          <div className="panel-title-row"><div><div className="section-kicker">PRODUCT TRENDS</div><h2>{selectedTrendProduct?.name ?? 'Select a product'}</h2></div><div className="trend-preview-actions">
            <select aria-label="Product to monitor" value={selectedTrendProduct?.id ?? ''} onChange={(event)=>setTrendProductId(event.target.value)}>{products.map((product)=><option value={product.id} key={product.id}>{product.name}</option>)}</select>
            <MetricToggle value={trendMetric} onChange={setTrendMetric}/>
            <button className="text-button" onClick={()=>openSection('product-trends')}>View trends <ArrowUpRight size={14}/></button>
          </div></div>
          {selectedTrendProduct ? <div className="trend-preview-grid"><div className="trend-preview-chart"><div className="trend-chart-caption"><span>Daily {trendMetric === 'quantity' ? 'units sold' : 'sales revenue'} · last 7 days</span><span>{productTrend?.sales_source === 'recorded' ? 'Recorded sales' : productTrend?.sales_source === 'illustrative' ? 'Illustrative demo data' : 'Loading trend…'}</span></div>{trendError ? <div className="trend-state error-text">{trendError}</div> : trendLoading && !trendMatchesSelection ? <div className="trend-state">Loading sales trend…</div> : trendMatchesSelection && productTrend ? <SalesTrendChart points={productTrend.sales} metric={trendMetric} compact/> : <div className="trend-state">Sales trend will appear here.</div>}</div>
            <div className="trend-stock-summary"><span className="section-kicker">CURRENT STOCK</span><strong>{selectedTrendProduct.stock}<small> units</small></strong><span className={`stock-badge ${selectedTrendProduct.stock<15?'low':''}`}>{selectedTrendProduct.stock<15?'Low stock':'In stock'}</span><button className="text-button" onClick={()=>openSection('product-trends')}>Stock change log <ArrowUpRight size={13}/></button></div></div>
          : <div className="trend-state">Product data is not available.</div>}
        </section>

        <div className="bottom-grid"><section className="panel inventory-panel" id="inventory"><div className="panel-title-row"><div><div className="section-kicker">PRODUCT SNAPSHOT</div><h2>Inventory & sales</h2></div><button className="text-button" onClick={()=>setMovementOpen((open)=>!open)}>{movementOpen ? 'Close movement form' : 'Record movement'} <ArrowUpRight size={13}/></button></div>{movementOpen && <form className="movement-form" onSubmit={(event)=>void recordMovement(event)}><label>Product<select value={movementProductId} onChange={(event)=>setMovementProductId(event.target.value)}>{products.map((product)=><option value={product.id} key={product.id}>{product.name}</option>)}</select></label><label>Type<select value={movementType} onChange={(event)=>setMovementType(event.target.value as 'receipt' | 'write_off')}><option value="receipt">Stock receipt (+)</option><option value="write_off">Write-off (−)</option></select></label><label>Units<input type="number" min="1" step="1" value={movementQuantity} onChange={(event)=>setMovementQuantity(event.target.value)} required /></label><label className="movement-note">Note (optional)<input value={movementNote} maxLength={500} onChange={(event)=>setMovementNote(event.target.value)} /></label><button className="primary-button">Save record</button></form>}<div className="table-wrap"><table><thead><tr><th>PRODUCT</th><th>PRICE</th><th>IN STOCK</th><th>7D SALES</th><th>VS LAST WEEK</th></tr></thead><tbody>{products.map(p=><tr key={p.id}><td><div className="table-product"><span className="table-emoji">{p.category==='Wellness'?'✳':'◉'}</span><span><b>{p.name}</b><small>{p.category}</small></span></div></td><td>{money(p.price)}</td><td><span className={`stock-badge ${p.stock<15?'low':''}`}>{p.stock} units</span></td><td>{p.units_sold_7d} units</td><td><span className={`change-text ${p.units_sold_7d<p.units_sold_prev_7d?'down':'up'}`}>{p.units_sold_7d<p.units_sold_prev_7d?<ArrowDownRight size={13}/>:<ArrowUpRight size={13}/>} {Math.round(Math.abs((p.units_sold_7d-p.units_sold_prev_7d)/Math.max(1,p.units_sold_prev_7d))*100)}%</span></td></tr>)}</tbody></table></div>{data?.movements?.length ? <div className="movement-history"><b>Recent manual stock records</b>{data.movements.slice(0,3).map((movement)=><span key={movement.id}>{movement.product_name} · {movement.movement_type === 'receipt' ? '+' : ''}{movement.quantity} · {new Date(movement.occurred_at).toLocaleDateString('en-AU')}</span>)}</div> : null}</section>
          <section className="panel audit-panel"><div className="panel-title-row"><div><div className="section-kicker">TRACEABILITY</div><h2>Recent activity</h2></div><button className="icon-button subtle" aria-label="Activity"><Activity size={16}/></button></div><div className="audit-list">{(data?.audit ?? []).slice(-4).reverse().map((entry)=><div className="audit-item" key={entry.id}><span className="audit-icon"><Check size={12}/></span><div><b>{entry.summary}</b><span>{new Date(entry.created_at).toLocaleString('en-AU',{hour:'2-digit',minute:'2-digit',day:'numeric',month:'short'})}</span></div></div>)}{!data?.audit?.length&&<div className="audit-empty">Analysis runs and owner decisions will be time-stamped here.</div>}</div></section></div>
        </div>

        <div className="workspace-module product-trends-module">
          <section className="panel product-trends-panel">
            <div className="panel-title-row trend-page-heading"><div><div className="section-kicker">PRODUCT TRENDS</div><h2>{selectedTrendProduct?.name ?? 'Product history'}</h2><p>Reporting period ends {new Date(`${reportDate}T12:00:00`).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}</p></div><span className="trend-source-pill">{productTrend?.sales_source === 'recorded' ? 'Recorded database sales' : 'Illustrative demo data'}</span></div>
            <div className="trend-controls">
              <label>Product<select aria-label="Select product" value={selectedTrendProduct?.id ?? ''} onChange={(event)=>setTrendProductId(event.target.value)}>{products.map((product)=><option value={product.id} key={product.id}>{product.name}</option>)}</select></label>
              <div className="trend-control-group"><span>Period</span><div className="segmented-control"><button className={trendDays===7?'selected':''} aria-pressed={trendDays===7} onClick={()=>setTrendDays(7)}>7 days</button><button className={trendDays===14?'selected':''} aria-pressed={trendDays===14} onClick={()=>setTrendDays(14)}>14 days</button></div></div>
              <div className="trend-control-group"><span>Measure</span><MetricToggle value={trendMetric} onChange={setTrendMetric}/></div>
            </div>
            {selectedTrendProduct ? <>
              <div className="trend-summary-cards"><div><span>Current stock</span><strong>{selectedTrendProduct.stock}<small> units</small></strong><em className={selectedTrendProduct.stock<15?'low':''}>{selectedTrendProduct.stock<15?'Low stock':'Available'}</em></div><div><span>{trendDays}-day {trendMetric === 'quantity' ? 'units sold' : 'sales revenue'}</span><strong>{trendMatchesSelection && productTrend ? trendMetric==='quantity' ? productTrend.sales.reduce((sum,point)=>sum+point.quantity,0).toLocaleString() : money(productTrend.sales.reduce((sum,point)=>sum+point.revenue,0)) : '—'}</strong><em>{productTrend?.sales_source==='recorded'?'Database records':productTrend?.sales_source==='illustrative'?'Illustrative distribution':'Loading'}</em></div><div><span>Recorded stock movements</span><strong>{productTrend?.product_id===selectedTrendProduct.id ? productTrend.movements.length : '—'}</strong><em>Receipts and write-offs</em></div></div>
              <section className="panel trend-chart-panel"><div className="trend-section-heading"><div><h3>Sales over time</h3><p>{productTrend?.sales_source==='recorded'?'Daily totals from saved sales records.':'Demo values are an illustrative distribution of the existing weekly totals.'}</p></div></div>{trendError ? <div className="trend-state error-text">{trendError}</div> : trendLoading && !trendMatchesSelection ? <div className="trend-state">Loading product history…</div> : trendMatchesSelection && productTrend ? <SalesTrendChart points={productTrend.sales} metric={trendMetric}/> : <div className="trend-state">Select a product to view its sales history.</div>}</section>
              <section className="panel movement-timeline-panel"><div className="trend-section-heading"><div><h3>Inventory changes</h3><p>Current stock is shown above. This timeline includes only movements recorded in the prototype.</p></div></div>{productTrend?.product_id===selectedTrendProduct.id && productTrend.movements.length ? <div className="movement-timeline">{productTrend.movements.map((movement)=><article className="movement-event" key={movement.id}><span className={`movement-event-mark ${movement.movement_type==='receipt'?'receipt':'write-off'}`}>{movement.movement_type==='receipt'?'+':'−'}</span><div><b>{movement.movement_type==='receipt'?'Stock received':'Stock written off'}</b><span>{movement.note || 'No note added'}</span></div><strong className={movement.movement_type==='receipt'?'positive':'negative'}>{movement.movement_type==='receipt'?'+':'−'}{Math.abs(movement.quantity)} units</strong><time>{new Date(movement.occurred_at).toLocaleDateString('en-AU',{day:'numeric',month:'short',year:'numeric'})}</time></article>)}</div> : <div className="trend-state">No recorded stock movements for this product yet.</div>}</section>
            </> : <div className="trend-state">Product data is not available.</div>}
          </section>
        </div>

        <div className="workspace-module agent-runs-module">
        <section className="panel run-panel"><div className="panel-title-row run-title"><div><div className="section-kicker">LATEST ANALYSIS</div><h2>{directAnswer?.title ?? (currentRun ? currentRun.recommendations[0]?.title : 'Your analysis workspace')}</h2></div>{directAnswer ? <span className="complete-badge completed"><Check size={13}/> Data answer</span> : currentRun && <span className={`complete-badge ${currentRun.status}`}>{currentRun.status === 'completed' ? <Check size={13}/> : <CircleHelp size={13}/>} {currentRun.status}</span>}</div>
          {directAnswer ? <div className="data-answer"><div className="run-meta"><span>Question</span><b>{question}</b><span className="meta-spacer"/><span className="demo-inline"><Database size={13}/>{directAnswer.data_source}</span></div><p>{directAnswer.answer}</p><div className="data-answer-evidence"><b>Compared products</b>{directAnswer.evidence.map((item)=><span key={item}><Check size={13}/>{item}</span>)}</div><small>Period: {directAnswer.period_start} to {directAnswer.period_end} · Direct database calculation; no LLM or agents used.</small></div> : currentRun ? <><div className="run-meta"><span><span className="workflow-pill">{currentRun.workflow.replace('_',' ')}</span></span><span>Started {time(currentRun.created_at)}</span><span className="meta-dot">·</span><span>{currentRun.agents.length} specialist agents</span>{currentRun.scope?.product_name && <><span className="meta-dot">·</span><span>Focused on {currentRun.scope.product_name}</span></>}<span className="meta-spacer"/><span className="demo-inline"><Database size={13}/>{currentRun.data_mode === 'supabase_llm' ? 'Supabase · Qwen' : currentRun.data_mode === 'supabase' ? 'Supabase records' : currentRun.data_mode === 'llm' ? 'Qwen · demo records' : 'Demo data'}</span></div>
            <div className="agent-track" role="group" aria-label="Select an agent summary">{currentRun.agents.map((a,i)=><button type="button" className={`agent-step ${selectedAgent === a.agent ? 'selected' : ''}`} aria-pressed={selectedAgent === a.agent} key={a.agent} onClick={() => setSelectedAgent(a.agent)}><span className={`step-icon ${a.status}`}>{a.status === 'failed' ? <X size={13}/> : <Check size={13}/>}</span>{i<currentRun.agents.length-1&&<span className="step-line"/>}<span className="agent-step-label"><b>{a.agent.replace(' Agent','')}</b><span>{a.status}</span></span></button>)}</div>
            <div className="result-grid"><div className="result-summary"><div className="summary-view-heading"><div className="section-kicker">{selectedAgentResult ? `${selectedAgentResult.agent.replace(' Agent','').toUpperCase()} AGENT SUMMARY` : 'MANAGER SUMMARY'}</div>{selectedAgentResult && <button type="button" className="manager-summary-link" onClick={() => setSelectedAgent(null)}>Manager summary</button>}</div><p>{summaryText}</p><div className="evidence-list">{summaryEvidence.map((e)=><span key={e}><Check size={13}/>{e}</span>)}{selectedAgentUnavailable && <span>No supporting evidence is available.</span>}</div>{selectedAgentResult?.limitations.length ? <div className="agent-note"><b>Agent note</b>{selectedAgentResult.limitations[0]}</div> : !selectedAgentResult && <div className="confidence"><span>Confidence</span><b>{activeRecommendation?.confidence}</b></div>}</div>
              <div className="recommendation-card"><div className="recommendation-head"><div className="recommendation-icon"><Sparkles size={16}/></div><div><span className="section-kicker">PRIORITY · {activeRecommendation?.priority.toUpperCase()}</span><b>{activeRecommendation?.title}</b></div></div><p>{activeRecommendation?.approval_note}</p>{activeRecommendation?.high_risk&&activeRecommendation.status==='pending_approval'?<div className="approval-actions"><button className="approve-button" disabled={decisionBusy} onClick={()=>void decide(activeRecommendation,'approve')}><Check size={14}/> Approve</button><button className="reject-button" disabled={decisionBusy} onClick={()=>openRejectForm(activeRecommendation)}><X size={14}/> Reject</button></div>:<span className={`status-label ${activeRecommendation?.status}`}>{activeRecommendation?.status.replace('_',' ')}</span>}</div></div>
            <div className="limitations"><span><CircleHelp size={14}/><b>Limitations</b></span>{currentRun.limitations.join(' ')}</div>
          </> : <div className="run-empty"><div className="empty-orbit"><Sparkles size={20}/></div><div><b>Your agents are ready when you are.</b><span>Start a workflow above to see a transparent, evidence-led analysis with approval controls.</span></div></div>}
        </section>

        <section className="panel history-panel" id="agent-runs"><div className="panel-title-row"><div><div className="section-kicker">ANALYSIS HISTORY</div><h2>Agent runs</h2></div><span className="workflow-pill">{allRuns.length} saved</span></div><div className="history-list">{allRuns.length ? allRuns.map((item)=><button className={`history-item ${currentRun?.id === item.id ? 'selected' : ''}`} aria-current={currentRun?.id === item.id ? 'true' : undefined} key={item.id} onClick={()=>{setRun(item); setDirectAnswer(null); setSelectedAgent(null); setAnalysisActivity(null); openSection('agent-runs')}}><span className={`history-status ${item.status}`}>{item.status}</span><span><b>{item.recommendations[0]?.title ?? item.workflow}</b><small>{item.workflow.replace('_',' ')} · {new Date(item.created_at).toLocaleString('en-AU')}</small></span><ArrowUpRight size={14}/></button>) : <div className="audit-empty">Start an analysis to create a traceable agent run.</div>}</div></section>
        </div>

        <div className="workspace-module approvals-module">
          <section className="panel approvals-panel" id="approvals"><div className="panel-title-row"><div><div className="section-kicker">HUMAN OVERSIGHT</div><h2>Approval queue</h2></div><span className="workflow-pill">{approvals.length} pending</span></div><div className="history-list">{approvals.length ? approvals.map(({run: approvalRun, recommendation})=><article className="approval-item" key={recommendation.id}><div><b>{recommendation.title}</b><small>{approvalRun.workflow.replace('_',' ')} · {recommendation.action}</small></div><div className="approval-actions"><button className="approve-button" disabled={decisionBusy} onClick={()=>{setRun(approvalRun); void decide(recommendation,'approve')}}><Check size={14}/> Approve</button><button className="reject-button" disabled={decisionBusy} onClick={()=>{setRun(approvalRun); openRejectForm(recommendation)}}><X size={14}/> Reject</button></div></article>) : <div className="audit-empty">No high-risk recommendations are awaiting owner approval.</div>}</div></section>
        </div>

        <div className="workspace-module customer-voice-module">
        <section className="panel customer-voice-panel" id="customer-voice">
          <div className="panel-title-row"><div><div className="section-kicker">CUSTOMER VOICE · {data?.feedback_count ?? 0} RECORDS</div><h2>Recent customer feedback</h2></div><div className="feedback-actions"><button className="text-button" disabled={busy} onClick={()=>void analyze(scenarios[3].prompt,'feedback_analysis')}>Analyze feedback <ArrowUpRight size={13}/></button><a className="text-button" href="/customer">Open customer form <ArrowUpRight size={13}/></a></div></div>
          <p className="feedback-privacy">Demo inbox. Contact details such as email addresses and phone numbers are masked before storage. Avoid entering names, addresses, or payment details. “Manual review” only creates an owner audit entry; it does not send an automatic reply.</p>
          {data?.insights?.feedback.record_count ? <p className="feedback-privacy">Themes: {Object.entries(data.insights.feedback.theme_counts).map(([theme,count])=>`${theme} (${count})`).join(' · ')}. Sentiment: {Object.entries(data.insights.feedback.sentiment_counts).map(([kind,count])=>`${kind} (${count})`).join(' · ')}.</p> : null}
          <div className="feedback-filters"><label>Product<select value={feedbackProductFilter} onChange={(event)=>setFeedbackProductFilter(event.target.value)}><option value="all">All products</option>{products.map((product)=><option key={product.id} value={product.id}>{product.name}</option>)}</select></label><label>Category<select value={feedbackCategoryFilter} onChange={(event)=>setFeedbackCategoryFilter(event.target.value)}><option value="all">All categories</option><option value="product">Product</option><option value="service">Service</option><option value="complaint">Complaint</option></select></label><label className="review-toggle"><input type="checkbox" checked={feedbackOnlyEscalated} onChange={(event)=>setFeedbackOnlyEscalated(event.target.checked)} /> Manual review only</label></div>
          <div className="feedback-list">{visibleFeedback.map((item)=>{const product=products.find((p)=>p.id===item.product_id);const classification=feedbackClassifications.get(item.id);const escalated=escalatedFeedback.has(item.id);return <article className="feedback-item" key={item.id}><div><b>{product?.name ?? 'Product feedback'}</b><span>{item.category} · {new Date(item.submitted_at).toLocaleDateString('en-AU')}</span></div><p>{item.content}</p><div className="feedback-tags"><span className={`feedback-priority ${classification?.priority ?? 'normal'}`}>{classification?.priority === 'high' ? 'high priority' : 'normal priority'}</span><span>{classification?.sentiment ?? 'unclassified'} · {(classification?.themes ?? ['other']).join(', ')}</span>{escalated ? <span className="reviewed-tag">Manual review</span> : <button onClick={()=>void escalateFeedback(item.id)}>Mark for manual review</button>}</div></article>})}{!visibleFeedback.length&&<div className="audit-empty">No feedback matches these filters.</div>}</div>
        </section>
        </div>
        <footer className="page-footer"><span><ShieldCheck size={14}/> AI outputs are advisory. You remain in control of every business decision.</span><span>SoloRetail AI · Stage 2 Prototype</span></footer>
      </div>
      {rejectingRecommendation && <div className="dialog-backdrop"><section className="rejection-dialog" role="dialog" aria-modal="true" aria-labelledby="rejection-title"><div className="section-kicker">HUMAN OVERSIGHT</div><h2 id="rejection-title">Reject recommendation</h2><p>{rejectingRecommendation.title}</p><form onSubmit={submitRejection}><label htmlFor="rejection-note">Reason for rejection <span>(optional)</span></label><textarea id="rejection-note" value={rejectionNote} onChange={(event)=>setRejectionNote(event.target.value)} maxLength={500} rows={4} placeholder="Add a note (optional)." autoFocus /><div className="rejection-note-count">{rejectionNote.length}/500</div><div className="rejection-dialog-actions"><button type="button" className="reject-button" disabled={decisionBusy} onClick={()=>{setRejectingRecommendation(null);setRejectionNote('')}}>Cancel</button><button type="submit" className="approve-button" disabled={decisionBusy}>{decisionBusy ? 'Saving…' : 'Confirm rejection'}</button></div></form></section></div>}
    </main>
  </div>
}

function Metric({title,value,change,note,icon,tone,down}:{title:string;value:string;change:string;note:string;icon:string;tone:string;down?:boolean}) { return <div className="metric-card"><div className="metric-top"><span>{title}</span><i className={`metric-icon ${tone}`}>{icon}</i></div><strong>{value}</strong><div className="metric-foot"><span className={down?'metric-down':'metric-up'}>{down?<ArrowDownRight size={13}/>:<ArrowUpRight size={13}/>} {change}</span><span>{note}</span></div></div> }

function MetricToggle({value,onChange}:{value:TrendMetric;onChange:(value:TrendMetric)=>void}) {
  return <div className="segmented-control metric-toggle"><button className={value==='quantity'?'selected':''} aria-pressed={value==='quantity'} onClick={()=>onChange('quantity')}>Units</button><button className={value==='revenue'?'selected':''} aria-pressed={value==='revenue'} onClick={()=>onChange('revenue')}>Revenue</button></div>
}

function SalesTrendChart({points,metric,compact=false}:{points:SalesPoint[];metric:TrendMetric;compact?:boolean}) {
  if (!points.length) return <div className="trend-state">No sales data is available for this period.</div>
  const width=760
  const height=compact?220:310
  const left=62, right=20, top=18, bottom=43
  const plotWidth=width-left-right
  const plotHeight=height-top-bottom
  const values=points.map((point)=>metric==='quantity'?point.quantity:point.revenue)
  const maxValue=Math.max(...values,1)
  const coords=values.map((value,index)=>({
    x:left+(points.length===1?plotWidth/2:index*plotWidth/(points.length-1)),
    y:top+plotHeight-(value/maxValue)*plotHeight,
    value,
  }))
  const coordinateString=coords.map((point)=>`${point.x},${point.y}`).join(' ')
  const formatValue=(value:number)=>metric==='quantity'?Math.round(value).toLocaleString('en-AU'):money(value)
  const labelStep=points.length>9?2:1
  const dateLabel=(value:string)=>new Date(`${value}T12:00:00`).toLocaleDateString('en-AU',{day:'numeric',month:'short'})
  return <div className={`sales-chart ${compact?'compact':''}`}>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metric==='quantity'?'Units sold':'Sales revenue'} by day`}>
      {[0,0.5,1].map((ratio)=><g key={ratio}><line className="chart-grid-line" x1={left} x2={width-right} y1={top+plotHeight*(1-ratio)} y2={top+plotHeight*(1-ratio)}/><text className="chart-axis-label" x={left-10} y={top+plotHeight*(1-ratio)+4} textAnchor="end">{formatValue(maxValue*ratio)}</text></g>)}
      <polygon className="chart-area" points={`${left},${top+plotHeight} ${coordinateString} ${width-right},${top+plotHeight}`}/>
      <polyline className="chart-line" points={coordinateString}/>
      {coords.map((point,index)=><g key={points[index].date}><circle className="chart-point" cx={point.x} cy={point.y} r={compact?4:5}><title>{dateLabel(points[index].date)} · {formatValue(point.value)}</title></circle>{(index%labelStep===0||index===points.length-1)&&<text className="chart-date-label" x={point.x} y={height-13} textAnchor="middle">{dateLabel(points[index].date)}</text>}</g>)}
    </svg>
  </div>
}

function AuthLoading() {
  return <main className="auth-page"><div className="auth-card auth-loading"><span className="brand-mark"><ShoppingBag size={20}/></span><b>Preparing your owner workspace…</b></div></main>
}

function LoginPage({ error, onSubmit }: { error: string; onSubmit: (email: string, password: string) => Promise<void> }) {
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Read the actual inputs so browser password-manager autofill works even
    // when the browser does not dispatch React change events.
    const fields = new FormData(event.currentTarget)
    const email = String(fields.get('username') ?? '')
    const password = String(fields.get('password') ?? '')
    setBusy(true)
    try { await onSubmit(email, password) }
    finally { setBusy(false) }
  }

  return <main className="auth-page"><section className="auth-card"><div className="brand-mark"><ShoppingBag size={20}/></div><div className="section-kicker">OWNER ACCESS</div><h1>Welcome back</h1><p>Sign in to view Harbour &amp; Co. operations and approve recommendations.</p>{error && <div className="alert error"><X size={16}/>{error}</div>}<form className="login-form" onSubmit={(event) => void submit(event)}><label>Email<input required name="username" type="email" autoComplete="username" placeholder="you@example.com" /></label><label>Password<input required name="password" type="password" autoComplete="current-password" placeholder="Your owner password" /></label><button className="primary-button login-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form><small>Save your credentials when your browser offers. Next time, use autofill and click Sign in. Your local owner session expires after 8 hours or when you sign out.</small></section></main>
}


function CustomerFeedbackPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [customerQuestion, setCustomerQuestion] = useState('')
  const [qaBusy, setQaBusy] = useState(false)
  const [qaError, setQaError] = useState('')
  const [qaResult, setQaResult] = useState<{ answer: string; evidence: string[]; limitations: string[] } | null>(null)
  const [productId, setProductId] = useState('')
  const [category, setCategory] = useState<'product' | 'service' | 'complaint'>('product')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    void fetch('/api/customer/products')
      .then((response) => readJson<{ products: Product[] }>(response))
      .then((body) => { setProducts(body.products); setProductId(body.products[0]?.id ?? '') })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load the product list.'))
  }, [])

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setQaBusy(true); setQaError(''); setQaResult(null)
    try {
      const response = await fetch('/api/customer/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: customerQuestion }),
      })
      const body = await readJson<{ answer: string; evidence: string[]; limitations: string[] }>(response)
      setQaResult(body)
    } catch (e) { setQaError(e instanceof Error ? e.message : 'Could not answer that question.') }
    finally { setQaBusy(false) }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true); setError(''); setSuccess('')
    try {
      const response = await fetch('/api/customer/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, category, content }),
      })
      const body = await readJson<{ contact_was_masked: boolean; message: string }>(response)
      setSuccess(body.contact_was_masked ? `${body.message} Email or phone details were masked before saving.` : body.message)
      setContent('')
    } catch (e) { setError(e instanceof Error ? e.message : 'Feedback could not be submitted.') }
    finally { setBusy(false) }
  }

  return <main className="customer-page">
    <header className="customer-header"><a className="customer-brand" href="/"><span className="brand-mark"><ShoppingBag size={19}/></span><span><b>SoloRetail</b><small>HARBOUR & CO.</small></span></a><a className="text-button" href="/">Store owner dashboard <ArrowUpRight size={13}/></a></header>
    <section className="customer-card customer-qa-card">
      <div className="section-kicker"><Package size={14}/> CUSTOMER HELP</div>
      <h1>Ask about products</h1>
      <p className="customer-intro">Ask about product details, price, stock, or current promotions. Answers use the store records available now.</p>
      <form className="customer-qa-form" onSubmit={(event)=>void ask(event)}>
        <label>Your question<textarea required minLength={3} maxLength={500} rows={2} value={customerQuestion} onChange={(event)=>setCustomerQuestion(event.target.value)} placeholder="e.g. How much is Harbour Blend Coffee?" /></label>
        <div className="feedback-form-footer"><span>Store policy details are only answered when configured.</span><button className="primary-button" disabled={qaBusy}>{qaBusy ? 'Looking up…' : 'Ask question'}</button></div>
      </form>
      {qaError && <div className="alert error"><X size={16}/>{qaError}</div>}
      {qaResult && <div className="customer-answer"><b>Answer</b><p>{qaResult.answer}</p>{qaResult.evidence.length > 0 && <div className="customer-answer-evidence"><span>Based on store records</span>{qaResult.evidence.map((item)=><small key={item}>{item}</small>)}</div>}{qaResult.limitations.map((item)=><small className="customer-answer-limit" key={item}>{item}</small>)}</div>}
    </section>
    <section className="customer-card">
      <div className="section-kicker"><MessageSquareText size={14}/> CUSTOMER VOICE</div>
      <h1>Share your feedback</h1>
      <p className="customer-intro">Tell Harbour & Co. about a product or service. Your feedback helps the store improve.</p>
      <div className="customer-notice"><ShieldCheck size={16}/><span>This is a demonstration form. Do not enter names, addresses, payment details, or other sensitive information. Email addresses and phone numbers are masked before the feedback is stored.</span></div>
      {error && <div className="alert error"><X size={16}/>{error}</div>}
      {success && <div className="alert success"><Check size={16}/>{success}</div>}
      <form className="feedback-form" onSubmit={(event)=>void submit(event)}>
        <label>Product<select required value={productId} onChange={(event)=>setProductId(event.target.value)}>{products.map((product)=><option key={product.id} value={product.id}>{product.name}</option>)}</select></label>
        <label>Feedback type<select value={category} onChange={(event)=>setCategory(event.target.value as typeof category)}><option value="product">Product</option><option value="service">Service</option><option value="complaint">Complaint</option></select></label>
        <label>Your feedback<textarea required minLength={5} maxLength={2000} rows={6} value={content} onChange={(event)=>setContent(event.target.value)} placeholder="What would you like the store to know?" /></label>
        <div className="feedback-form-footer"><span>{content.length}/2000 characters · email/phone masking runs before storage</span><button className="primary-button" disabled={busy || !products.length}>{busy ? 'Submitting…' : 'Submit feedback'}</button></div>
      </form>
    </section>
  </main>
}

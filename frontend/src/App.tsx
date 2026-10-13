import { useEffect, useState, type FormEvent } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, Bell, Check, ChevronDown, CircleHelp, Clock3, Database, LayoutDashboard, LogOut, Menu, MessageSquareText, Package, Play, ShieldCheck, Sparkles, Store, X } from 'lucide-react'

type Agent = { agent: string; status: string; summary: string; evidence: string[]; limitations: string[] }
type Recommendation = { id: string; title: string; priority: string; action: string; evidence: string[]; confidence: string; high_risk: boolean; status: string; approval_note: string }
type Product = { id: string; name: string; category: string; price: number; stock: number; units_sold_7d: number; units_sold_prev_7d: number }
type FeedbackRecord = { id: string; product_id: string; category: string; content: string; submitted_at: string }
type Run = { id: string; question: string; workflow: string; status: string; data_mode: string; created_at: string; agents: Agent[]; recommendations: Recommendation[]; limitations: string[]; scope?: { product_id?: string; product_name?: string } }
type ProductInsight = { product_id: string; weekly_change_percent: number; estimated_cover_days: number | null; latest_week_revenue: number; risk: string }
type FeedbackClassification = { id: string; themes: string[]; sentiment: string; priority: string }
type InventoryMovement = { id: string; product_id: string; product_name: string; movement_type: string; quantity: number; note: string; occurred_at: string; updated_stock?: number }
type Dashboard = { data_mode: string; products: Product[]; feedback_count: number; feedback: FeedbackRecord[]; runs: Run[]; audit: { id: string; event: string; summary: string; created_at: string; feedback_id?: string }[]; movements: InventoryMovement[]; insights?: { products: ProductInsight[]; feedback: { theme_counts: Record<string, number>; sentiment_counts: Record<string, number>; record_count: number; classifications: FeedbackClassification[] } } }
type WorkspaceSection = 'overview' | 'agent-runs' | 'approvals' | 'customer-voice'
type OwnerSession = { email: string; name: string; role: string }

const scenarios = [
  { key: 'sales_decline', label: 'Sales decline', prompt: 'Why are Harbour Blend Coffee sales falling, and what should I do?' },
  { key: 'overstock', label: 'Overstock', prompt: 'How should I clear slow-moving Coastal Oat Biscuits stock?' },
  { key: 'demand_spike', label: 'Demand spike', prompt: 'Wattle Hand Balm demand suddenly spiked. How do I avoid a stock-out?' },
  { key: 'feedback_analysis', label: 'Customer feedback', prompt: 'Analyse customer feedback and suggest improvements.' },
]

const money = (amount: number) => new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(amount)
const time = (value: string) => new Date(value).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' })

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
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [simulateFailure, setSimulateFailure] = useState(false)
  const [activeSection, setActiveSection] = useState<WorkspaceSection>('overview')
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

  async function refresh() {
    try { const response = await ownerFetch('/api/dashboard'); setData(await readJson<Dashboard>(response)); setError('') }
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
          const body = await readJson<{ session: OwnerSession }>(response)
          setSession(body.session)
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
    if (prompt.trim().length < 5) { setError('Enter a little more detail so the Manager Agent can scope the analysis.'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await ownerFetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: prompt, workflow, product_id: analysisProductId || null, simulate_failures: simulateFailure ? ['Marketing Agent'] : [] }) })
      const body = await readJson<Run>(response)
      setRun(body); setQuestion(prompt); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Analysis failed.') }
    finally { setBusy(false) }
  }

  async function decide(rec: Recommendation, decision: 'approve' | 'reject') {
    try {
      const response = await ownerFetch(`/api/recommendations/${rec.id}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note: '' }) })
      const body = await readJson<{ recommendation: Recommendation; message: string }>(response)
      setRun((current) => current ? { ...current, recommendations: current.recommendations.map((item) => item.id === rec.id ? body.recommendation : item) } : current)
      setNotice(body.message); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Approval failed.') }
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
  const productInsights = new Map((data?.insights?.products ?? []).map((item) => [item.product_id, item]))
  const feedbackClassifications = new Map((data?.insights?.feedback.classifications ?? []).map((item) => [item.id, item]))
  const escalatedFeedback = new Set((data?.audit ?? []).filter((entry) => entry.event === 'feedback_escalated' && entry.feedback_id).map((entry) => entry.feedback_id))
  const storedRuns = data?.runs ?? []
  const currentRun = run ?? storedRuns[storedRuns.length - 1] ?? null
  const activeRecommendation = currentRun?.recommendations[0]
  const currentUnits = products.reduce((sum, p) => sum + p.units_sold_7d, 0)
  const previousUnits = products.reduce((sum, p) => sum + p.units_sold_prev_7d, 0)
  const unitChange = previousUnits ? Math.round((currentUnits - previousUnits) / previousUnits * 100) : 0
  const currentRevenue = products.reduce((sum, p) => sum + p.units_sold_7d * p.price, 0)
  const previousRevenue = products.reduce((sum, p) => sum + p.units_sold_prev_7d * p.price, 0)
  const revenueChange = previousRevenue ? Math.round((currentRevenue - previousRevenue) / previousRevenue * 100) : 0
  const allRuns = Array.from(new Map([run, ...storedRuns].filter((item): item is Run => Boolean(item)).map((item) => [item.id, item])).values())
  const approvals = allRuns.flatMap((item) => item.recommendations.filter((recommendation) => recommendation.high_risk && recommendation.status === 'pending_approval').map((recommendation) => ({ run: item, recommendation })))
  const supabaseMode = data?.data_mode === 'supabase' || data?.data_mode === 'supabase_llm'
  const llmMode = data?.data_mode === 'llm' || data?.data_mode === 'supabase_llm'
  const dataSourceTitle = supabaseMode ? (llmMode ? 'Supabase data · Qwen analysis' : 'Supabase database is active') : (llmMode ? 'Qwen analysis is active' : 'Demo data is active')
  const dataSourceDescription = supabaseMode ? 'Products, sales and feedback are loaded from your Supabase project. Seeded business records are illustrative.' : (llmMode ? 'Qwen analyses illustrative sample records only; nothing is connected to a live store.' : 'These figures are illustrative sample records. Nothing here is connected to a live store.')
  const dataSourceTag = supabaseMode ? (llmMode ? 'SUPABASE · QWEN' : 'SUPABASE') : (llmMode ? 'LLM · DEMO DATA' : 'LOCAL DEMO')
  const sectionTitle: Record<WorkspaceSection, string> = { overview: 'Overview', 'agent-runs': 'Agent runs', approvals: 'Approvals', 'customer-voice': 'Customer voice' }
  const maxSales = Math.max(...products.map((product) => product.units_sold_7d), 1)
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
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Store size={19} /></div><div><b>SoloRetail</b><span>AI OPERATIONS</span></div></div>
      <div className="store-switch"><div className="store-avatar">H</div><div><b>Harbour & Co.</b><span>Independent retailer</span></div><ChevronDown size={15} /></div>
      <div className="nav-label">WORKSPACE</div>
      <nav>
        <button className={`nav-item ${activeSection === 'overview' ? 'active' : ''}`} onClick={() => openSection('overview')}><LayoutDashboard size={17}/> Overview</button>
        <button className={`nav-item ${activeSection === 'agent-runs' ? 'active' : ''}`} onClick={() => openSection('agent-runs')}><Activity size={17}/> Agent runs <span className="nav-count">{allRuns.length}</span></button>
        <button className={`nav-item ${activeSection === 'approvals' ? 'active' : ''}`} onClick={() => openSection('approvals')}><ShieldCheck size={17}/> Approvals {approvals.length > 0 && <i className="nav-dot"/>}</button>
        <button className={`nav-item ${activeSection === 'customer-voice' ? 'active' : ''}`} onClick={() => openSection('customer-voice')}><MessageSquareText size={17}/> Customer voice</button>
      </nav>
      <div className="sidebar-bottom"><button className="help-card" onClick={()=>setNotice('Demo guide: choose a workflow, inspect evidence and limitations, then approve or reject only high-risk recommendations.')}><CircleHelp size={17}/><div><b>Need a hand?</b><span>View the demo guide</span></div></button><div className="profile-wrap"><button className="profile" onClick={() => setAccountMenuOpen((open) => !open)} aria-expanded={accountMenuOpen}><div className="profile-avatar">JM</div><div><b>{session?.name ?? 'Jordan Mitchell'}</b><span>{session?.role ?? 'Store owner'}</span></div><ChevronDown size={14}/></button>{accountMenuOpen && <div className="account-menu"><b>{session?.name ?? 'Jordan Mitchell'}</b><span>{authRequired ? session?.email : 'Local prototype access'}</span>{authRequired ? <button onClick={() => void signOut()}><LogOut size={14}/> Sign out</button> : <small>Set `AUTH_REQUIRED=true` to enable owner sign-in.</small>}</div>}</div></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="topbar-left"><button className="sidebar-toggle" aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'} title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'} onClick={() => setSidebarOpen((open) => !open)}><Menu size={18}/></button><div className="breadcrumbs">Workspace <span>/</span> <b>{sectionTitle[activeSection]}</b></div></div><div className="top-actions"><span className="live-pill"><i/> {supabaseMode ? 'Supabase environment' : 'Demo environment'}</span><button className="icon-button" aria-label="Notifications" onClick={()=>setNotice(`${approvals.length} high-risk recommendation${approvals.length === 1 ? '' : 's'} awaiting owner review.`)}><Bell size={17}/><i/></button><div className="top-avatar">JM</div></div></header>
      <div className={`page-content module-${activeSection}`}>
        {error && <div className="alert error"><X size={16}/>{error}<button onClick={() => void refresh()}>Retry</button></div>}
        {notice && <div className="alert success"><Check size={16}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss">×</button></div>}
        <div className="workspace-module overview-module">
        <div className="page-heading" id="overview"><div><div className="eyebrow">STORE OPERATIONS <span>·</span> SYDNEY, AU</div><h1>Good morning, Jordan <span>✳</span></h1><p>Here’s what’s happening across your store today.</p></div><button className="date-filter" onClick={()=>setNotice('All sales comparisons use the latest 7 days against the preceding 7 days.')}><Clock3 size={15}/> Last 7 days <ChevronDown size={14}/></button></div>
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
            <div className="scenario-row">{scenarios.map((s)=><button key={s.key} className="scenario-chip" disabled={busy} onClick={()=>void analyze(s.prompt,s.key)}><span className={`scenario-dot ${s.key}`}/>{s.label}<ArrowUpRight size={12}/></button>)}</div>
          </section>
          <section className="panel watch-panel"><div className="panel-title-row"><div><div className="section-kicker">STORE PULSE</div><h2>Needs a closer look</h2></div><a className="text-button" href="#inventory">View all <ArrowUpRight size={13}/></a></div>
            {products.filter(p=>p.stock<15 || p.units_sold_7d<p.units_sold_prev_7d).map(p=>{const insight=productInsights.get(p.id);return <div className="watch-item" key={p.id}><div className="product-icon">{p.category==='Wellness'?'✳':'◉'}</div><div className="watch-info"><b>{p.name}</b><span>{insight?.estimated_cover_days != null ? `${insight.estimated_cover_days} days cover · ${insight.risk.replace(/_/g,' ')}` : `${p.units_sold_7d} sold this week`}</span></div><span className={`trend ${p.units_sold_7d<p.units_sold_prev_7d?'negative':'positive'}`}>{p.units_sold_7d<p.units_sold_prev_7d?<ArrowDownRight size={14}/>:<ArrowUpRight size={14}/>} {insight ? `${insight.weekly_change_percent > 0 ? '+' : ''}${insight.weekly_change_percent}%` : p.units_sold_7d-p.units_sold_prev_7d}</span></div>})}
            {!products.length && <div className="empty-small">Store metrics will appear when the API is running.</div>}
          </section>
        </div>

        <section className="panel performance-panel"><div className="panel-title-row"><div><div className="section-kicker">EXPLAINABLE VIEW</div><h2>7-day unit sales by product</h2></div><span className="workflow-pill">not a forecast</span></div><div className="performance-chart">{products.map((product) => <div className="performance-row" key={product.id}><span>{product.name}</span><div className="performance-track"><i style={{ width: `${Math.max(4, product.units_sold_7d / maxSales * 100)}%` }}/></div><b>{product.units_sold_7d}</b></div>)}</div><p className="chart-note">Bars compare the latest 7-day sales records only. Use the product scope above to ask a follow-up question on one item.</p></section>

        <div className="bottom-grid"><section className="panel inventory-panel" id="inventory"><div className="panel-title-row"><div><div className="section-kicker">PRODUCT SNAPSHOT</div><h2>Inventory & sales</h2></div><button className="text-button" onClick={()=>setMovementOpen((open)=>!open)}>{movementOpen ? 'Close movement form' : 'Record movement'} <ArrowUpRight size={13}/></button></div>{movementOpen && <form className="movement-form" onSubmit={(event)=>void recordMovement(event)}><label>Product<select value={movementProductId} onChange={(event)=>setMovementProductId(event.target.value)}>{products.map((product)=><option value={product.id} key={product.id}>{product.name}</option>)}</select></label><label>Type<select value={movementType} onChange={(event)=>setMovementType(event.target.value as 'receipt' | 'write_off')}><option value="receipt">Stock receipt (+)</option><option value="write_off">Write-off (−)</option></select></label><label>Units<input type="number" min="1" step="1" value={movementQuantity} onChange={(event)=>setMovementQuantity(event.target.value)} required /></label><label className="movement-note">Note (optional)<input value={movementNote} maxLength={500} onChange={(event)=>setMovementNote(event.target.value)} /></label><button className="primary-button">Save record</button></form>}<div className="table-wrap"><table><thead><tr><th>PRODUCT</th><th>PRICE</th><th>IN STOCK</th><th>7D SALES</th><th>VS LAST WEEK</th></tr></thead><tbody>{products.map(p=><tr key={p.id}><td><div className="table-product"><span className="table-emoji">{p.category==='Wellness'?'✳':'◉'}</span><span><b>{p.name}</b><small>{p.category}</small></span></div></td><td>{money(p.price)}</td><td><span className={`stock-badge ${p.stock<15?'low':''}`}>{p.stock} units</span></td><td>{p.units_sold_7d} units</td><td><span className={`change-text ${p.units_sold_7d<p.units_sold_prev_7d?'down':'up'}`}>{p.units_sold_7d<p.units_sold_prev_7d?<ArrowDownRight size={13}/>:<ArrowUpRight size={13}/>} {Math.round(Math.abs((p.units_sold_7d-p.units_sold_prev_7d)/Math.max(1,p.units_sold_prev_7d))*100)}%</span></td></tr>)}</tbody></table></div>{data?.movements?.length ? <div className="movement-history"><b>Recent manual stock records</b>{data.movements.slice(0,3).map((movement)=><span key={movement.id}>{movement.product_name} · {movement.movement_type === 'receipt' ? '+' : ''}{movement.quantity} · {new Date(movement.occurred_at).toLocaleDateString('en-AU')}</span>)}</div> : null}</section>
          <section className="panel audit-panel"><div className="panel-title-row"><div><div className="section-kicker">TRACEABILITY</div><h2>Recent activity</h2></div><button className="icon-button subtle" aria-label="Activity"><Activity size={16}/></button></div><div className="audit-list">{(data?.audit ?? []).slice(-4).reverse().map((entry)=><div className="audit-item" key={entry.id}><span className="audit-icon"><Check size={12}/></span><div><b>{entry.summary}</b><span>{new Date(entry.created_at).toLocaleString('en-AU',{hour:'2-digit',minute:'2-digit',day:'numeric',month:'short'})}</span></div></div>)}{!data?.audit?.length&&<div className="audit-empty">Analysis runs and owner decisions will be time-stamped here.</div>}</div></section></div>
        </div>

        <div className="workspace-module agent-runs-module">
        <section className="panel run-panel"><div className="panel-title-row run-title"><div><div className="section-kicker">LATEST ANALYSIS</div><h2>{currentRun ? currentRun.recommendations[0]?.title : 'Your analysis workspace'}</h2></div>{currentRun && <span className={`complete-badge ${currentRun.status}`}>{currentRun.status === 'completed' ? <Check size={13}/> : <CircleHelp size={13}/>} {currentRun.status}</span>}</div>
          {currentRun ? <><div className="run-meta"><span><span className="workflow-pill">{currentRun.workflow.replace('_',' ')}</span></span><span>Started {time(currentRun.created_at)}</span><span className="meta-dot">·</span><span>{currentRun.agents.length} specialist agents</span>{currentRun.scope?.product_name && <><span className="meta-dot">·</span><span>Focused on {currentRun.scope.product_name}</span></>}<span className="meta-spacer"/><span className="demo-inline"><Database size={13}/>{currentRun.data_mode === 'supabase_llm' ? 'Supabase · Qwen' : currentRun.data_mode === 'supabase' ? 'Supabase records' : currentRun.data_mode === 'llm' ? 'Qwen · demo records' : 'Demo data'}</span></div>
            <div className="agent-track">{currentRun.agents.map((a,i)=><div className="agent-step" key={a.agent}><div className={`step-icon ${a.status}`}>{a.status === 'failed' ? <X size={13}/> : <Check size={13}/>}</div>{i<currentRun.agents.length-1&&<div className="step-line"/>}<div><b>{a.agent.replace(' Agent','')}</b><span>{a.status}</span></div></div>)}</div>
            <div className="result-grid"><div className="result-summary"><div className="section-kicker">MANAGER SUMMARY</div><p>{currentRun.recommendations[0]?.action}</p><div className="evidence-list">{currentRun.recommendations[0]?.evidence.slice(0,2).map((e)=><span key={e}><Check size={13}/>{e}</span>)}</div><div className="confidence"><span>Confidence</span><b>{currentRun.recommendations[0]?.confidence}</b></div></div>
              <div className="recommendation-card"><div className="recommendation-head"><div className="recommendation-icon"><Sparkles size={16}/></div><div><span className="section-kicker">PRIORITY · {activeRecommendation?.priority.toUpperCase()}</span><b>{activeRecommendation?.title}</b></div></div><p>{activeRecommendation?.approval_note}</p>{activeRecommendation?.high_risk&&activeRecommendation.status==='pending_approval'?<div className="approval-actions"><button className="approve-button" onClick={()=>void decide(activeRecommendation,'approve')}><Check size={14}/> Approve</button><button className="reject-button" onClick={()=>void decide(activeRecommendation,'reject')}><X size={14}/> Reject</button></div>:<span className={`status-label ${activeRecommendation?.status}`}>{activeRecommendation?.status.replace('_',' ')}</span>}</div></div>
            <div className="limitations"><span><CircleHelp size={14}/><b>Limitations</b></span>{currentRun.limitations.join(' ')}</div>
          </> : <div className="run-empty"><div className="empty-orbit"><Sparkles size={20}/></div><div><b>Your agents are ready when you are.</b><span>Start a workflow above to see a transparent, evidence-led analysis with approval controls.</span></div></div>}
        </section>

        <section className="panel history-panel" id="agent-runs"><div className="panel-title-row"><div><div className="section-kicker">ANALYSIS HISTORY</div><h2>Agent runs</h2></div><span className="workflow-pill">{allRuns.length} saved</span></div><div className="history-list">{allRuns.length ? allRuns.slice(0,8).map((item)=><button className="history-item" key={item.id} onClick={()=>{setRun(item); openSection('agent-runs')}}><span className={`history-status ${item.status}`}>{item.status}</span><span><b>{item.recommendations[0]?.title ?? item.workflow}</b><small>{item.workflow.replace('_',' ')} · {new Date(item.created_at).toLocaleString('en-AU')}</small></span><ArrowUpRight size={14}/></button>) : <div className="audit-empty">Start an analysis to create a traceable agent run.</div>}</div></section>
        </div>

        <div className="workspace-module approvals-module">
          <section className="panel approvals-panel" id="approvals"><div className="panel-title-row"><div><div className="section-kicker">HUMAN OVERSIGHT</div><h2>Approval queue</h2></div><span className="workflow-pill">{approvals.length} pending</span></div><div className="history-list">{approvals.length ? approvals.map(({run: approvalRun, recommendation})=><article className="approval-item" key={recommendation.id}><div><b>{recommendation.title}</b><small>{approvalRun.workflow.replace('_',' ')} · {recommendation.action}</small></div><div className="approval-actions"><button className="approve-button" onClick={()=>{setRun(approvalRun); void decide(recommendation,'approve')}}><Check size={14}/> Approve</button><button className="reject-button" onClick={()=>{setRun(approvalRun); void decide(recommendation,'reject')}}><X size={14}/> Reject</button></div></article>) : <div className="audit-empty">No high-risk recommendations are awaiting owner approval.</div>}</div></section>
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
    </main>
  </div>
}

function Metric({title,value,change,note,icon,tone,down}:{title:string;value:string;change:string;note:string;icon:string;tone:string;down?:boolean}) { return <div className="metric-card"><div className="metric-top"><span>{title}</span><i className={`metric-icon ${tone}`}>{icon}</i></div><strong>{value}</strong><div className="metric-foot"><span className={down?'metric-down':'metric-up'}>{down?<ArrowDownRight size={13}/>:<ArrowUpRight size={13}/>} {change}</span><span>{note}</span></div></div> }

function AuthLoading() {
  return <main className="auth-page"><div className="auth-card auth-loading"><span className="brand-mark"><Store size={20}/></span><b>Preparing your owner workspace…</b></div></main>
}

function LoginPage({ error, onSubmit }: { error: string; onSubmit: (email: string, password: string) => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    try { await onSubmit(email, password) }
    finally { setBusy(false) }
  }

  return <main className="auth-page"><section className="auth-card"><div className="brand-mark"><Store size={20}/></div><div className="section-kicker">OWNER ACCESS</div><h1>Welcome back</h1><p>Sign in to view Harbour &amp; Co. operations and approve recommendations.</p>{error && <div className="alert error"><X size={16}/>{error}</div>}<form className="login-form" onSubmit={(event) => void submit(event)}><label>Email<input required type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></label><label>Password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Your owner password" /></label><button className="primary-button login-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form><small>Your local owner session expires after 8 hours or when you sign out.</small></section></main>
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
    <header className="customer-header"><a className="customer-brand" href="/"><span className="brand-mark"><Store size={19}/></span><span><b>SoloRetail</b><small>HARBOUR & CO.</small></span></a><a className="text-button" href="/">Store owner dashboard <ArrowUpRight size={13}/></a></header>
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

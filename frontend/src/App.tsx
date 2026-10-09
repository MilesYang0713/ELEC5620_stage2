import { useEffect, useState } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, Bell, Check, ChevronDown, CircleHelp, Clock3, Database, LayoutDashboard, MessageSquareText, Package, Play, ShieldCheck, Sparkles, Store, X } from 'lucide-react'

type Agent = { agent: string; status: string; summary: string; evidence: string[]; limitations: string[] }
type Recommendation = { id: string; title: string; priority: string; action: string; evidence: string[]; confidence: string; high_risk: boolean; status: string; approval_note: string }
type Run = { id: string; question: string; workflow: string; status: string; data_mode: string; created_at: string; agents: Agent[]; recommendations: Recommendation[]; limitations: string[] }
type Dashboard = { data_mode: string; products: { id: string; name: string; category: string; price: number; stock: number; units_sold_7d: number; units_sold_prev_7d: number }[]; feedback_count: number; runs: Run[]; audit: { id: string; event: string; summary: string; created_at: string }[] }

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

  async function refresh() {
    try { const response = await fetch('/api/dashboard'); setData(await readJson<Dashboard>(response)); setError('') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not reach the API. Start the backend or Docker Compose, then refresh.') }
  }
  useEffect(() => { void refresh() }, [])

  async function analyze(prompt = question, workflow?: string) {
    if (prompt.trim().length < 5) { setError('Enter a little more detail so the Manager Agent can scope the analysis.'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: prompt, workflow }) })
      const body = await readJson<Run>(response)
      setRun(body); setQuestion(prompt); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Analysis failed.') }
    finally { setBusy(false) }
  }

  async function decide(rec: Recommendation, decision: 'approve' | 'reject') {
    try {
      const response = await fetch(`/api/recommendations/${rec.id}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note: '' }) })
      const body = await readJson<{ recommendation: Recommendation; message: string }>(response)
      setRun((current) => current ? { ...current, recommendations: current.recommendations.map((item) => item.id === rec.id ? body.recommendation : item) } : current)
      setNotice(body.message); await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Approval failed.') }
  }

  const products = data?.products ?? []
  const storedRuns = data?.runs ?? []
  const currentRun = run ?? storedRuns[storedRuns.length - 1] ?? null
  const activeRecommendation = currentRun?.recommendations[0]
  const avgUnits = products.length ? products.reduce((sum, p) => sum + p.units_sold_7d, 0) : 0
  const approvals = currentRun?.recommendations.filter((r) => r.high_risk) ?? []

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Store size={19} /></div><div><b>SoloRetail</b><span>AI OPERATIONS</span></div></div>
      <div className="store-switch"><div className="store-avatar">H</div><div><b>Harbour & Co.</b><span>Independent retailer</span></div><ChevronDown size={15} /></div>
      <div className="nav-label">WORKSPACE</div>
      <nav><a className="nav-item active"><LayoutDashboard size={17}/> Overview</a><a className="nav-item"><Activity size={17}/> Agent runs <span className="nav-count">{data?.runs.length ?? 0}</span></a><a className="nav-item"><ShieldCheck size={17}/> Approvals {approvals.length > 0 && <i className="nav-dot"/>}</a><a className="nav-item"><MessageSquareText size={17}/> Customer voice</a></nav>
      <div className="sidebar-bottom"><div className="help-card"><CircleHelp size={17}/><div><b>Need a hand?</b><span>View the demo guide</span></div></div><div className="profile"><div className="profile-avatar">JM</div><div><b>Jordan Mitchell</b><span>Store owner</span></div><ChevronDown size={14}/></div></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs">Workspace <span>/</span> <b>Overview</b></div><div className="top-actions"><span className="live-pill"><i/> Demo environment</span><button className="icon-button" aria-label="Notifications"><Bell size={17}/><i/></button><div className="top-avatar">JM</div></div></header>
      <div className="page-content">
        <div className="page-heading"><div><div className="eyebrow">THURSDAY, 9 OCTOBER 2026 <span>·</span> SYDNEY, AU</div><h1>Good morning, Jordan <span>✳</span></h1><p>Here’s what’s happening across your store today.</p></div><button className="date-filter"><Clock3 size={15}/> Last 7 days <ChevronDown size={14}/></button></div>
        <div className="demo-banner"><div className="demo-icon"><Database size={16}/></div><div><b>{data?.data_mode === 'llm' ? 'Qwen analysis is active' : 'Demo data is active'}</b><span>{data?.data_mode === 'llm' ? 'Qwen analyses illustrative sample records only; nothing is connected to a live store.' : 'These figures are illustrative sample records. Nothing here is connected to a live store.'}</span></div><span className="demo-tag">{data?.data_mode === 'llm' ? 'LLM · DEMO DATA' : 'LOCAL DEMO'}</span></div>
        {error && <div className="alert error"><X size={16}/>{error}<button onClick={() => void refresh()}>Retry</button></div>}
        {notice && <div className="alert success"><Check size={16}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss">×</button></div>}
        <section className="metric-grid">
          <Metric title="Sales · last 7 days" value={money(products.reduce((s,p)=>s+p.units_sold_7d*p.price,0))} change="12.8%" down note="vs previous 7 days" icon="↘" tone="sage"/>
          <Metric title="Units sold" value={String(avgUnits)} change="8.2%" down note="vs previous 7 days" icon="▤" tone="lavender"/>
          <Metric title="Products to watch" value={String(products.filter(p=>p.stock<15).length)} change="2 need attention" note="low stock or declining sales" icon="!" tone="peach"/>
          <Metric title="Customer feedback" value={String(data?.feedback_count ?? 0)} change="2 new" note="in the last 7 days" icon="♡" tone="blue"/>
        </section>

        <div className="content-grid">
          <section className="panel analysis-panel">
            <div className="panel-heading"><div><div className="section-kicker"><Sparkles size={14}/> AI BUSINESS ASSISTANT</div><h2>What would you like to work on?</h2><p>Ask a question or start with a common workflow.</p></div><span className="manager-badge"><i/> Manager ready</span></div>
            <div className="composer"><textarea value={question} onChange={(e)=>setQuestion(e.target.value)} onKeyDown={(e)=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();void analyze()}}} placeholder="e.g. Why are my coffee sales slowing down?" rows={2}/><div className="composer-bottom"><span>AI suggestions are advisory only</span><button className="primary-button" disabled={busy} onClick={()=>void analyze()}><Play size={14} fill="currentColor"/>{busy?'Analysing…':'Run analysis'}</button></div></div>
            <div className="scenario-row">{scenarios.map((s)=><button key={s.key} className="scenario-chip" disabled={busy} onClick={()=>void analyze(s.prompt,s.key)}><span className={`scenario-dot ${s.key}`}/>{s.label}<ArrowUpRight size={12}/></button>)}</div>
          </section>
          <section className="panel watch-panel"><div className="panel-title-row"><div><div className="section-kicker">STORE PULSE</div><h2>Needs a closer look</h2></div><button className="text-button">View all <ArrowUpRight size={13}/></button></div>
            {products.filter(p=>p.stock<15 || p.units_sold_7d<p.units_sold_prev_7d).map(p=><div className="watch-item" key={p.id}><div className="product-icon">{p.category==='Wellness'?'✳':'◉'}</div><div className="watch-info"><b>{p.name}</b><span>{p.stock<15?`${p.stock} units in stock · low cover`:`${p.units_sold_7d} sold this week`}</span></div><span className={`trend ${p.units_sold_7d<p.units_sold_prev_7d?'negative':'positive'}`}>{p.units_sold_7d<p.units_sold_prev_7d?<ArrowDownRight size={14}/>:<ArrowUpRight size={14}/>} {p.units_sold_7d-p.units_sold_prev_7d>0?'+':''}{p.units_sold_7d-p.units_sold_prev_7d}</span></div>)}
            {!products.length && <div className="empty-small">Store metrics will appear when the API is running.</div>}
          </section>
        </div>

        <section className="panel run-panel"><div className="panel-title-row run-title"><div><div className="section-kicker">LATEST ANALYSIS</div><h2>{currentRun ? currentRun.recommendations[0]?.title : 'Your analysis workspace'}</h2></div>{currentRun && <span className={`complete-badge ${currentRun.status}`}>{currentRun.status === 'completed' ? <Check size={13}/> : <CircleHelp size={13}/>} {currentRun.status}</span>}</div>
          {currentRun ? <><div className="run-meta"><span><span className="workflow-pill">{currentRun.workflow.replace('_',' ')}</span></span><span>Started {time(currentRun.created_at)}</span><span className="meta-dot">·</span><span>{currentRun.agents.length} specialist agents</span><span className="meta-spacer"/><span className="demo-inline"><Database size={13}/>{currentRun.data_mode === 'llm' ? 'Qwen · demo records' : 'Demo data'}</span></div>
            <div className="agent-track">{currentRun.agents.map((a,i)=><div className="agent-step" key={a.agent}><div className={`step-icon ${a.status}`}>{a.status === 'failed' ? <X size={13}/> : <Check size={13}/>}</div>{i<currentRun.agents.length-1&&<div className="step-line"/>}<div><b>{a.agent.replace(' Agent','')}</b><span>{a.status}</span></div></div>)}</div>
            <div className="result-grid"><div className="result-summary"><div className="section-kicker">MANAGER SUMMARY</div><p>{currentRun.recommendations[0]?.action}</p><div className="evidence-list">{currentRun.recommendations[0]?.evidence.slice(0,2).map((e)=><span key={e}><Check size={13}/>{e}</span>)}</div><div className="confidence"><span>Confidence</span><b>{currentRun.recommendations[0]?.confidence}</b></div></div>
              <div className="recommendation-card"><div className="recommendation-head"><div className="recommendation-icon"><Sparkles size={16}/></div><div><span className="section-kicker">PRIORITY · {activeRecommendation?.priority.toUpperCase()}</span><b>{activeRecommendation?.title}</b></div></div><p>{activeRecommendation?.approval_note}</p>{activeRecommendation?.high_risk&&activeRecommendation.status==='pending_approval'?<div className="approval-actions"><button className="approve-button" onClick={()=>void decide(activeRecommendation,'approve')}><Check size={14}/> Approve</button><button className="reject-button" onClick={()=>void decide(activeRecommendation,'reject')}><X size={14}/> Reject</button></div>:<span className={`status-label ${activeRecommendation?.status}`}>{activeRecommendation?.status.replace('_',' ')}</span>}</div></div>
            <div className="limitations"><span><CircleHelp size={14}/><b>Limitations</b></span>{currentRun.limitations.join(' ')}</div>
          </> : <div className="run-empty"><div className="empty-orbit"><Sparkles size={20}/></div><div><b>Your agents are ready when you are.</b><span>Start a workflow above to see a transparent, evidence-led analysis with approval controls.</span></div></div>}
        </section>

        <div className="bottom-grid"><section className="panel inventory-panel"><div className="panel-title-row"><div><div className="section-kicker">PRODUCT SNAPSHOT</div><h2>Inventory & sales</h2></div><button className="text-button">All products <ArrowUpRight size={13}/></button></div><div className="table-wrap"><table><thead><tr><th>PRODUCT</th><th>PRICE</th><th>IN STOCK</th><th>7D SALES</th><th>VS LAST WEEK</th></tr></thead><tbody>{products.map(p=><tr key={p.id}><td><div className="table-product"><span className="table-emoji">{p.category==='Wellness'?'✳':'◉'}</span><span><b>{p.name}</b><small>{p.category}</small></span></div></td><td>{money(p.price)}</td><td><span className={`stock-badge ${p.stock<15?'low':''}`}>{p.stock} units</span></td><td>{p.units_sold_7d} units</td><td><span className={`change-text ${p.units_sold_7d<p.units_sold_prev_7d?'down':'up'}`}>{p.units_sold_7d<p.units_sold_prev_7d?<ArrowDownRight size={13}/>:<ArrowUpRight size={13}/>} {Math.round(Math.abs((p.units_sold_7d-p.units_sold_prev_7d)/Math.max(1,p.units_sold_prev_7d))*100)}%</span></td></tr>)}</tbody></table></div></section>
          <section className="panel audit-panel"><div className="panel-title-row"><div><div className="section-kicker">TRACEABILITY</div><h2>Recent activity</h2></div><button className="icon-button subtle" aria-label="Activity"><Activity size={16}/></button></div><div className="audit-list">{(data?.audit ?? []).slice(-4).reverse().map((entry)=><div className="audit-item" key={entry.id}><span className="audit-icon"><Check size={12}/></span><div><b>{entry.summary}</b><span>{new Date(entry.created_at).toLocaleString('en-AU',{hour:'2-digit',minute:'2-digit',day:'numeric',month:'short'})}</span></div></div>)}{!data?.audit?.length&&<div className="audit-empty">Analysis runs and owner decisions will be time-stamped here.</div>}</div></section></div>
        <footer className="page-footer"><span><ShieldCheck size={14}/> AI outputs are advisory. You remain in control of every business decision.</span><span>SoloRetail AI · Stage 2 Prototype</span></footer>
      </div>
    </main>
  </div>
}

function Metric({title,value,change,note,icon,tone,down}:{title:string;value:string;change:string;note:string;icon:string;tone:string;down?:boolean}) { return <div className="metric-card"><div className="metric-top"><span>{title}</span><i className={`metric-icon ${tone}`}>{icon}</i></div><strong>{value}</strong><div className="metric-foot"><span className={down?'metric-down':'metric-up'}>{down?<ArrowDownRight size={13}/>:<ArrowUpRight size={13}/>} {change}</span><span>{note}</span></div></div> }

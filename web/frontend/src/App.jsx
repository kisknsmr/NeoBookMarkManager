import React, { useState } from 'react'

function NodeView({node, depth=0}){
  return (
    <div className={`node ${node.type}`} style={{paddingLeft: depth*12}}>
      <div className="node-title">{node.title || '(untitled)'} {node.url ? <a href={node.url} target="_blank" rel="noreferrer">🔗</a> : null}</div>
      {node.children && node.children.length>0 && (
        <div className="node-children">
          {node.children.map((c, i)=> <NodeView key={i} node={c} depth={depth+1} />)}
        </div>
      )}
    </div>
  )
}

export default function App(){
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [path, setPath] = useState('')
  const [error, setError] = useState(null)

  async function load(){
    setLoading(true)
    setError(null)
    try{
      const url = '/api/bookmarks' + (path ? ('?path='+encodeURIComponent(path)) : '')
      const res = await fetch(url)
      const j = await res.json()
      if(res.ok) setData(j.root)
      else setError(j.error || 'Error')
    }catch(e){
      setError(String(e))
    }finally{ setLoading(false) }
  }

  return (
    <div className="app-root">
      <header className="topbar">
        <div className="brand">Bookmark Studio</div>
        <div className="top-actions">
          <input value={path} onChange={e=>setPath(e.target.value)} placeholder="Leave empty for sample" />
          <button onClick={load} className="btn">Load</button>
        </div>
      </header>

      <div className="content">
        <div className="left">
          <div className="workspace">
            <div className="workspace-header">
              <div className="workspace-title">Bookmarks</div>
              <div className="view-toggle">View</div>
            </div>
            <div className="table">
              {loading && <div className="card">Loading…</div>}
              {error && <div className="card error">{error}</div>}
              {data ? <NodeView node={data} /> : <div style={{padding:16}}>No data loaded</div>}
            </div>
          </div>
        </div>
        <aside className="right">
          <div className="sidebar">
            <div className="section">
              <div className="section-header">
                <div className="section-title">File</div>
                <div className="section-note">Actions</div>
              </div>
              <div className="grid">
                <button className="btn primary">Save</button>
                <button className="btn ghost">Open</button>
              </div>
            </div>

            <div className="section">
              <div className="section-header">
                <div className="section-title">AI Classify</div>
                <div className="section-note">Model</div>
              </div>
              <div className="grid">
                <button className="btn primary">Smart</button>
                <button className="btn tonal">Rules</button>
              </div>
            </div>

            <div className="section">
              <div className="section-header">
                <div className="section-title">Other</div>
                <div className="section-note">Utilities</div>
              </div>
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
                <button className="btn ghost">Test</button>
                <button className="btn ghost">Exit</button>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

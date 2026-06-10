import { useState, useRef, useMemo } from "react";
import { auditRecruitmentPiece, RECRUITMENT_TYPES } from "./permCompliance";

export function permSplitLines(t){return t.replace(/\r\n/g,'\n').split('\n');}

export const PBULLET=/^[\s]*([-\u2022*]+|\d+[.)]|[a-zA-Z][.)])\s*/;

export function permNorm(t){return permSplitLines(t).map(l=>l.replace(PBULLET,'').trim()).filter(l=>l.length>0).join(' ');}

export function permTok(t,s){return s?Array.from(t):(t.match(/(\s+|[A-Za-z0-9_]+|[^A-Za-z0-9_\s])/g)??[]);}

export function pLcs(l,r,ci){const eq=(a,b)=>ci?a.toLowerCase()===b.toLowerCase():a===b;const m=Array.from({length:l.length+1},()=>new Array(r.length+1).fill(0));for(let i=l.length-1;i>=0;i--)for(let j=r.length-1;j>=0;j--)m[i][j]=eq(l[i],r[j])?m[i+1][j+1]+1:Math.max(m[i+1][j],m[i][j+1]);return m;}

export function pDiffTok(a,b,s,ci){const at=permTok(a,s),bt=permTok(b,s),m=pLcs(at,bt,ci),ar=[],br=[];const eq=(x,y)=>ci?x.toLowerCase()===y.toLowerCase():x===y;let ai=0,bi=0;while(ai<at.length&&bi<bt.length){if(eq(at[ai],bt[bi])){ar.push({t:at[ai],c:false});br.push({t:bt[bi],c:false});ai++;bi++;}else if(m[ai+1][bi]>=m[ai][bi+1])ar.push({t:at[ai++],c:true});else br.push({t:bt[bi++],c:true});}while(ai<at.length)ar.push({t:at[ai++],c:true});while(bi<bt.length)br.push({t:bt[bi++],c:true});return{ar,br};}

export function pDiffLines(a,b,s,ci){const al=permSplitLines(a),bl=permSplitLines(b);const eqLine=(x,y)=>ci?x.toLowerCase()===y.toLowerCase():x===y;const m=pLcs(al,bl,ci),ops=[];let ai=0,bi=0;while(ai<al.length&&bi<bl.length){if(eqLine(al[ai],bl[bi])){ops.push({t:'eq',s:al[ai]});ai++;bi++;}else if(m[ai+1][bi]>=m[ai][bi+1])ops.push({t:'rm',s:al[ai++]});else ops.push({t:'add',s:bl[bi++]});}while(ai<al.length)ops.push({t:'rm',s:al[ai++]});while(bi<bl.length)ops.push({t:'add',s:bl[bi++]});const lines=[];let oi=0,rn=1,cn=1;while(oi<ops.length){const cur=ops[oi];if(cur.t==='eq'){lines.push({rn,cn,rt:[{t:cur.s,c:false}],ct:[{t:cur.s,c:false}],ch:false});rn++;cn++;oi++;continue;}const rm=[],add=[];while(oi<ops.length&&ops[oi].t!=='eq'){const p=ops[oi++];(p.t==='rm'?rm:add).push(p.s);}const sz=Math.max(rm.length,add.length);for(let k=0;k<sz;k++){const{ar,br}=pDiffTok(rm[k]??'',add[k]??'',s,ci);lines.push({rn:k<rm.length?rn:null,cn:k<add.length?cn:null,rt:ar,ct:br,ch:true});if(k<rm.length)rn++;if(k<add.length)cn++;}}return lines;}

export function pSummarize(field,ref,cmp,strict,igFmt){const r=igFmt?permNorm(ref):ref,c=igFmt?permNorm(cmp):cmp,lines=pDiffLines(r,c,strict,igFmt),changed=lines.filter(l=>l.ch).length,exact=igFmt?r.toLowerCase()===c.toLowerCase():r===c;return{field,exact,status:exact?'Exact Match':'Differences Found',detail:exact?(igFmt?'Match when formatting ignored.':'Texts are identical.'):`${changed} differing line${changed===1?'':'s'}.`,lines};}

export function PTokens({tokens,kind}){if(!tokens.length)return <span style={{color:'var(--text3)',fontStyle:'italic'}}>(no text)</span>;return tokens.map((tk,i)=><span key={i} style={tk.c?{display:'inline',borderRadius:4,padding:'0 1px',background:kind==='reference'?'var(--red-dim)':'var(--green-dim)',color:kind==='reference'?'var(--red)':'var(--green)'}:{}}>{tk.t}</span>);}

export function pParseCur(v){const m=(v||'').replace(/,/g,'').match(/-?\d+(?:\.\d+)?/);return m?Number(m[0]):null;}

export function pFmt(v){const n=pParseCur(v);if(n===null)return v||'(empty)';return n.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2});}

export const PS={
  card:{background:'var(--bg2)',border:'1px solid var(--border)',borderRadius:'var(--radius-lg)',padding:18},
  cardRef:{background:'var(--bg3)',border:'1px solid var(--border)',borderRadius:'var(--radius-lg)',padding:18},
  label:{display:'block',marginBottom:8,fontSize:11,fontWeight:600,color:'var(--text2)'},
  input:{width:'100%',padding:'10px 12px',borderRadius:'var(--radius)',border:'1px solid var(--border)',background:'var(--bg)',color:'var(--text)',font:'inherit',fontSize:12},
  textarea:{width:'100%',padding:'12px 14px',borderRadius:'var(--radius-lg)',border:'1px solid var(--border)',background:'var(--bg)',color:'var(--text)',font:'inherit',fontSize:12,lineHeight:1.6,resize:'vertical',fontFamily:"'DM Mono',monospace"},
  badge:(match)=>({display:'inline-flex',alignItems:'center',borderRadius:999,padding:'4px 10px',fontSize:10,fontWeight:600,whiteSpace:'nowrap',background:match===null?'var(--bg4)':match?'var(--green-dim)':'var(--red-dim)',color:match===null?'var(--text3)':match?'var(--green)':'var(--red)'}),
  diffCell:{minWidth:0,padding:'10px 12px',border:'1px solid var(--border)',borderRadius:'var(--radius)',background:'var(--bg)'},
};

export function PermDiffPanel({res,title}){
  return(
    <div style={PS.card}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
        <div><div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>Highlighted Differences</div><div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>{title} Review</div></div>
        <span style={PS.badge(res.exact)}>{res.status}</span>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:8,fontSize:10,fontWeight:600,letterSpacing:'.08em',textTransform:'uppercase',color:'var(--text3)',padding:'0 4px'}}>
        <div>Reference</div><div>Comparison</div>
      </div>
      <div style={{display:'grid',gap:8}}>
        {res.lines.map((line,i)=>(
          <div key={i} style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
            <div style={{...PS.diffCell,borderColor:line.ch?'var(--red)':'var(--border)'}}>
              <div style={{fontSize:10,fontWeight:600,color:'var(--text3)',fontFamily:"'DM Mono',monospace",marginBottom:6}}>{line.rn?`Line ${line.rn}`:' '}</div>
              <pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.6}}><PTokens tokens={line.rt} kind="reference"/></pre>
            </div>
            <div style={{...PS.diffCell,borderColor:line.ch?'var(--red)':'var(--border)'}}>
              <div style={{fontSize:10,fontWeight:600,color:'var(--text3)',fontFamily:"'DM Mono',monospace",marginBottom:6}}>{line.cn?`Line ${line.cn}`:' '}</div>
              <pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.6}}><PTokens tokens={line.ct} kind="comparison"/></pre>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Drop-target textarea ──────────────────────────────────────────────────────
// onPwdDrop(file)    — called when a PDF is dropped and this box handles PWD parsing
// onLetterDrop(file) — called when a PDF is dropped and this box handles letter parsing
// If neither is provided, falls back to generic /api/extract-text plain text dump.

export function DropTextarea({ value, onChange, minHeight=260, borderColor, background, placeholder, onPwdDrop, onLetterDrop, acceptDocx=false }){
  const [dragging, setDragging] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractErr, setExtractErr] = useState('');
  const fileRef = useRef(null);

  const isDocx = (f) => /\.docx$/i.test(f.name || '') ||
    f.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  const handleFile = async (file) => {
    // PWD/letter drops are PDF-only; the generic recruitment path also takes .docx.
    const okPdf = file && file.type === 'application/pdf';
    const okDocx = acceptDocx && file && isDocx(file);
    if (!okPdf && !okDocx) {
      setExtractErr(acceptDocx ? 'Only PDF or Word (.docx) files are supported.' : 'Only PDF files are supported for drag-and-drop.');
      return;
    }
    setExtracting(true);
    setExtractErr('');
    try {
      if (onPwdDrop) {
        await onPwdDrop(file);
      } else if (onLetterDrop) {
        await onLetterDrop(file);
      } else {
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch('/api/extract-text', { method: 'POST', body: fd });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: 'Server error' }));
          throw new Error(err.detail || 'Extraction failed');
        }
        const data = await resp.json();
        if (data.text) onChange({ target: { value: data.text } });
        else setExtractErr('No text could be extracted from this PDF.');
      }
    } catch(e) {
      setExtractErr('Extraction failed: ' + e.message);
    } finally {
      setExtracting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const dropStyle = {
    position: 'relative',
    borderRadius: 'var(--radius)',
    transition: 'box-shadow 0.15s',
    ...(dragging ? { boxShadow: '0 0 0 2px var(--amber)' } : {})
  };

  return (
    <div style={dropStyle}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <textarea
        style={{
          ...PS.textarea,
          minHeight,
          borderColor: dragging ? 'var(--amber)' : (borderColor || 'var(--border)'),
          background: background || 'var(--bg)',
          opacity: extracting ? 0.5 : 1,
          transition: 'border-color 0.15s, opacity 0.2s',
        }}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={extracting}
      />
      {extracting && (
        <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:'var(--radius)',background:'rgba(0,0,0,0.18)',pointerEvents:'none'}}>
          <div style={{display:'flex',alignItems:'center',gap:8,padding:'8px 16px',background:'var(--bg2)',borderRadius:20,border:'1px solid var(--border)',fontSize:12,color:'var(--text2)'}}>
            <div style={{width:12,height:12,border:'2px solid var(--amber)',borderTopColor:'transparent',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>
            Extracting…
          </div>
        </div>
      )}
      {dragging && (
        <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:'var(--radius)',background:'rgba(0,0,0,0.22)',pointerEvents:'none'}}>
          <div style={{padding:'10px 20px',background:'var(--bg2)',borderRadius:20,border:'1px solid var(--amber)',fontSize:13,color:'var(--amber)',fontWeight:600}}>
            {acceptDocx ? 'Drop document to extract' : 'Drop PDF to extract'}
          </div>
        </div>
      )}
      <input ref={fileRef} type="file" accept={acceptDocx ? 'application/pdf,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'application/pdf'} style={{display:'none'}} onChange={e => handleFile(e.target.files[0])}/>
      {extractErr && <div style={{marginTop:6,fontSize:11,color:'var(--red)'}}>{extractErr}</div>}
    </div>
  );
}

// ── Experience Verification Modal ────────────────────────────────────────────
// TODO (Future): Implement automated experience comparison — compare the total
// months of experience across all uploaded letters against the years required
// by the PWD minimum requirements. Note: the language used in PERMs often
// phrases requirements as "X years in the field" vs "X years in specific
// skills", so automated comparison will need to account for that distinction.
// See journal.txt for context.

export function expHighlightKeywords(text, keywords){
  if(!keywords||keywords.length===0)return [{text,hl:false}];
  const escaped=keywords.map(k=>k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  const re=new RegExp(`(${escaped.join('|')})`, 'gi');
  const parts=text.split(re);
  return parts.map(p=>({text:p,hl:new RegExp(escaped.join('|'),'i').test(p)}));
}

export function ExpHighlightedText({text,keywords}){
  const parts=expHighlightKeywords(text,keywords);
  return(
    <span>
      {parts.map((p,i)=>
        p.hl
          ?<mark key={i} style={{background:'#f59e0b44',color:'var(--amber)',borderRadius:3,padding:'0 2px',fontWeight:600}}>{p.text}</mark>
          :<span key={i}>{p.text}</span>
      )}
    </span>
  );
}

export function ExperienceVerificationModal({pwdText,requirementsText,letters,onClose,onSaveLetter,onRemoveLetter}){
  const [activeIdx,setActiveIdx]=useState(0);
  const [uploading,setUploading]=useState(false);
  const [uploadErr,setUploadErr]=useState('');
  const fileRef=useRef(null);

  const activeLetter=letters[activeIdx]||null;

  // Extract meaningful words and short phrases from the requirements text.
  // We pull: capitalized terms, numbers+units ("3 years"), and any quoted phrases.
  const reqKeywords=useMemo(()=>{
    if(!requirementsText)return[];
    const words=new Set();
    // All words 3+ chars, excluding very common stop words
    const stop=new Set(['the','and','or','for','with','that','this','must','have',
      'will','shall','may','can','not','any','all','each','such','from','into',
      'which','been','has','its','their','they','are','was','were','but','per',
      'years','year','months','month','experience','required','requires','including',
      'knowledge','ability','skills','skill','related','equivalent','degree','field',
      'work','working','use','using','using','used','other','than','more','least',
      'one','two','three','four','five','six']);
    const wordRe=/\b([A-Za-z][A-Za-z0-9.+#\-]{2,})\b/g;
    let m;
    while((m=wordRe.exec(requirementsText))!==null){
      const w=m[1];
      if(!stop.has(w.toLowerCase()))words.add(w);
    }
    return Array.from(words);
  },[requirementsText]);

  // For each keyword, check if it appears (case-insensitive) in the active letter
  const kwResults=useMemo(()=>{
    if(!activeLetter||!reqKeywords.length)return[];
    const haystack=(activeLetter.fullText||'').toLowerCase();
    return reqKeywords.map(kw=>({
      word:kw,
      found:haystack.includes(kw.toLowerCase())
    }));
  },[activeLetter,reqKeywords]);

  const highlightWords=[...reqKeywords];

  const uploadLetter=async(file)=>{
    if(!file)return;
    setUploading(true);setUploadErr('');
    try{
      const fd=new FormData();
      fd.append('file',file);
      const resp=await fetch('/api/extract-experience-letter',{method:'POST',body:fd});
      if(!resp.ok){
        const err=await resp.json().catch(()=>({detail:'Server error'}));
        throw new Error(err.detail||'Extraction failed');
      }
      const parsed=await resp.json();
      onSaveLetter({fileName:file.name,...parsed,saved:false},null);
      setActiveIdx(letters.length);
    }catch(e){
      setUploadErr('Could not extract letter: '+e.message);
    }finally{
      setUploading(false);
      if(fileRef.current)fileRef.current.value='';
    }
  };

  const switchLetter=(i)=>{setActiveIdx(i);};
  const totalSavedMonths=letters.filter(l=>l.saved).reduce((s,l)=>s+(l.months||0),0);

  return(
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.72)',zIndex:9000,display:'flex',alignItems:'stretch',justifyContent:'center'}} onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
      <div style={{display:'flex',flexDirection:'column',background:'var(--bg)',width:'100%',maxWidth:1400,margin:'0 auto',height:'100vh',overflow:'hidden'}}>
        {/* Header */}
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'14px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0}}>
          <div>
            <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:2}}>Experience Verification</div>
            <div style={{fontSize:16,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>PWD Requirements vs. Experience Letters</div>
          </div>
          <div style={{display:'flex',gap:10,alignItems:'center'}}>
            {letters.length>0&&<div style={{fontSize:12,color:'var(--text2)',padding:'4px 12px',background:'var(--bg3)',borderRadius:20,border:'1px solid var(--border)'}}>
              <strong style={{color:'var(--green)'}}>{(totalSavedMonths/12).toFixed(1)} yrs</strong> saved across {letters.filter(l=>l.saved).length} letter{letters.filter(l=>l.saved).length!==1?'s':''}
            </div>}
            <input ref={fileRef} type="file" accept="application/pdf" style={{display:'none'}} onChange={e=>uploadLetter(e.target.files[0])}/>
            <button onClick={()=>fileRef.current?.click()} disabled={uploading} style={{fontSize:11,padding:'5px 14px',background:uploading?'var(--bg3)':'var(--green-dim)',color:uploading?'var(--text3)':'var(--green)',border:uploading?'1px solid var(--border)':'1px solid #34d39944',borderRadius:20,cursor:uploading?'default':'pointer',display:'flex',alignItems:'center',gap:6}}>
              {uploading?<><div style={{width:10,height:10,border:'1.5px solid currentColor',borderTopColor:'transparent',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>  Extracting…</>:<>+ Upload Letter</>}
            </button>
            <button onClick={onClose} style={{background:'var(--bg3)',border:'1px solid var(--border)',borderRadius:8,color:'var(--text2)',cursor:'pointer',padding:'5px 12px',fontSize:12}}>✕ Close</button>
          </div>
        </div>
        {uploadErr&&<div style={{padding:'8px 24px',background:'var(--red-dim)',color:'var(--red)',fontSize:12,flexShrink:0}}>{uploadErr}</div>}

        {/* Letter tabs */}
        {letters.length>0&&(
          <div style={{display:'flex',gap:6,padding:'10px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0,overflowX:'auto'}}>
            {letters.map((l,i)=>(
              <button key={i} onClick={()=>switchLetter(i)} style={{fontSize:11,padding:'4px 14px',borderRadius:20,cursor:'pointer',whiteSpace:'nowrap',background:activeIdx===i?'var(--amber-dim)':'var(--bg3)',color:activeIdx===i?'var(--amber)':'var(--text3)',border:activeIdx===i?'1px solid #f59e0b44':'1px solid var(--border)',fontWeight:activeIdx===i?600:400}}>
                {l.employerName||l.fileName||`Letter ${i+1}`}{l.months!=null&&<span style={{marginLeft:6,opacity:.7}}>{l.months}mo</span>}{l.saved&&<span style={{marginLeft:4,color:'var(--green)'}}>✓</span>}
              </button>
            ))}
          </div>
        )}

        {/* Columns */}
        <div style={{display:'flex',flex:1,overflow:'hidden',minHeight:0}}>
          {/* Left — PWD */}
          <div style={{flex:'0 0 42%',overflow:'auto',padding:'20px 24px',borderRight:'1px solid var(--border)'}}>
            <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:8}}>PWD — Minimum Requirements</div>
            {pwdText
              ?<pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.8,color:'var(--text)'}}>
                <ExpHighlightedText text={pwdText} keywords={highlightWords}/>
              </pre>
              :<div style={{color:'var(--text3)',fontSize:13,fontStyle:'italic'}}>No requirements text — paste the Minimum Requirements on the main page first.</div>
            }
          </div>

          {/* Right — Letter */}
          <div style={{flex:1,display:'flex',flexDirection:'column',overflow:'hidden'}}>
            {!activeLetter&&(
              <div style={{flex:1,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',padding:40,color:'var(--text3)'}}>
                <div style={{fontSize:32,marginBottom:12}}>📄</div>
                <div style={{fontSize:14,marginBottom:6}}>No letters uploaded yet</div>
                <div style={{fontSize:12}}>Click <strong>+ Upload Letter</strong> to add an experience verification letter PDF.</div>
              </div>
            )}
            {activeLetter&&(
              <>
                {/* Metadata bar */}
                <div style={{padding:'12px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0,display:'flex',gap:16,alignItems:'center',flexWrap:'wrap'}}>
                  <div><div style={{fontSize:10,color:'var(--text3)',marginBottom:2}}>Employer</div><div style={{fontSize:13,fontWeight:600,color:'var(--text)'}}>{activeLetter.employerName||'—'}</div></div>
                  <div><div style={{fontSize:10,color:'var(--text3)',marginBottom:2}}>Title</div><div style={{fontSize:13,color:'var(--text)'}}>{activeLetter.jobTitle||'—'}</div></div>
                  <div><div style={{fontSize:10,color:'var(--text3)',marginBottom:2}}>Period</div><div style={{fontSize:13,color:'var(--text)'}}>{activeLetter.startDate||'?'} – {activeLetter.endDate||'?'}</div></div>
                  {activeLetter.months!=null&&<div style={{padding:'4px 14px',borderRadius:20,background:'var(--amber-dim)',border:'1px solid #f59e0b44',color:'var(--amber)',fontSize:12,fontWeight:600}}>{activeLetter.months} mo ({(activeLetter.months/12).toFixed(1)} yrs)</div>}
                  <div style={{marginLeft:'auto',display:'flex',gap:8,alignItems:'center'}}>
                    {!activeLetter.saved
                      ?<button onClick={()=>onSaveLetter({...activeLetter,saved:true},activeIdx)} style={{fontSize:11,padding:'5px 14px',background:'var(--green-dim)',color:'var(--green)',border:'1px solid #34d39944',borderRadius:20,cursor:'pointer'}}>✓ Save Time</button>
                      :<span style={{fontSize:11,padding:'5px 10px',color:'var(--green)'}}>✓ Time saved</span>
                    }
                    <button onClick={()=>{onRemoveLetter(activeIdx);setActiveIdx(Math.max(0,activeIdx-1));}} style={{fontSize:11,padding:'5px 10px',background:'var(--red-dim)',color:'var(--red)',border:'1px solid #f8717144',borderRadius:20,cursor:'pointer'}}>✕</button>
                  </div>
                </div>

                {/* Keyword check panel */}
                {kwResults.length>0&&(
                  <div style={{padding:'12px 24px',borderBottom:'1px solid var(--border)',background:'var(--bg2)',flexShrink:0}}>
                    <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:8}}>Requirements Keyword Check</div>
                    <div style={{display:'flex',flexWrap:'wrap',gap:6}}>
                      {kwResults.map(({word,found})=>(
                        <span key={word} style={{
                          fontSize:11,padding:'2px 10px',borderRadius:20,fontWeight:500,
                          background:found?'var(--green-dim)':'var(--red-dim)',
                          color:found?'var(--green)':'var(--red)',
                          border:found?'1px solid #34d39944':'1px solid #f8717144',
                        }}>
                          {found?'✓':'✗'} {word}
                        </span>
                      ))}
                    </div>
                    <div style={{marginTop:8,fontSize:11,color:'var(--text3)'}}>
                      {kwResults.filter(r=>r.found).length} of {kwResults.length} requirement keywords found in this letter
                    </div>
                  </div>
                )}

                {/* Letter text */}
                <div style={{flex:1,overflow:'auto',padding:'20px 24px'}}>
                  <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:8}}>Letter Text</div>
                  <pre style={{margin:0,whiteSpace:'pre-wrap',wordBreak:'break-word',fontFamily:"'DM Mono',monospace",fontSize:12,lineHeight:1.8,color:'var(--text)'}}>
                    <ExpHighlightedText text={activeLetter.fullText||activeLetter.duties||'No text extracted.'} keywords={highlightWords}/>
                  </pre>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Equal Pay Transparency (EPT) data ────────────────────────────────────────
// Source: AILA Practice Pointer, Guide to Equal Pay Transparency Laws (Oct 2025)
// AILA Doc. No. 25110603

export const EPT_DATA = {
  'CA': {
    state:'California', effectiveDate:'01/01/2023', citation:'SB 1162; Cal. Labor Code § 432.3',
    employerThreshold:'15+ employees (even if only 1 is in CA)',
    wagReq:'Pay scale (min/max salary or hourly range). No bonuses or benefits required. SB 642 (10/08/2025) revised definition to "good-faith estimate."',
    postingReq:'Pay scale must be included in all job postings (internal and external).',
    benefitsReq:false,
    longArm:true, longArmNote:'May apply to nationwide remote postings even without CA office if employer has 15+ employees.',
    remoteCoverage:'Remote jobs outside CA where worker reports to a CA supervisor or work site.',
    notes:'',
  },
  'CO': {
    state:'Colorado', effectiveDate:'01/01/2021', citation:'Equal Pay for Equal Work Act (EPEWA); POST Rules, 7 CCR 1103-18 (eff. 07/01/2024)',
    employerThreshold:'1+ employee in Colorado',
    wagReq:'Min/max annual or hourly range. General description of bonuses, commissions, and major benefits required.',
    postingReq:'Required for each new job, promotion, transfer, or other employment opportunity. Public and internal postings.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Remote jobs outside CO covered if employer has CO employees. Does not apply to jobs performed entirely outside CO.',
    notes:'Benefits and bonus description required — more than most states.',
  },
  'HI': {
    state:'Hawaii', effectiveDate:'01/01/2024', citation:'ACT 203 (SB1057), Hawaii Equal Pay Act',
    employerThreshold:'50+ employees (within or outside Hawaii)',
    wagReq:'Salary range or hourly rate reasonably reflecting actual expected compensation.',
    postingReq:'Any "job listing" (not specifically defined).',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'Not specified.',
    notes:'Excludes internal transfers/promotions and public jobs under collective bargaining.',
  },
  'IL': {
    state:'Illinois', effectiveDate:'01/01/2025', citation:'820 ILCS 112/ — Equal Pay Act of 2003',
    employerThreshold:'15+ employees (within or outside Illinois)',
    wagReq:'Wage/salary or range. General description of benefits, bonuses, stock options, and other incentives.',
    postingReq:'Any specific job posting. A hyperlink to the pay/benefits information is acceptable.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Jobs performed outside IL covered if employee reports to an IL supervisor, office, or work site.',
    notes:'Benefits and bonus description required.',
  },
  'MD': {
    state:'Maryland', effectiveDate:'10/01/2024', citation:'HB 649 and SB 525',
    employerThreshold:'Employers of any size',
    wagReq:'Min/max hourly rate or salary. No open-ended ranges (e.g., "up to $100k" not permitted). Other compensation excluded.',
    postingReq:'All job postings, internal and external. If multiple locations/seniority levels, separate range per location/level. Employer must complete and post a benefits/compensation form (link acceptable).',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Jobs physically performed at least partially in MD. Occasional work in state (e.g., meetings) excluded.',
    notes:'Applies to employers of any size — lowest threshold among covered states. Form available at labor.maryland.gov.',
  },
  'MA': {
    state:'Massachusetts', effectiveDate:'10/29/2025', citation:'An Act Relative to Salary Range Transparency (H.4890)',
    employerThreshold:'25+ employees with primary place of work in MA (prior calendar year average)',
    wagReq:'"Pay range" = salary or hourly range employer reasonably and in good faith expects to pay. Bonuses/commissions not required.',
    postingReq:'Any advertisement or job posting intended to recruit for a specific position.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'All positions where primary place of work is MA, including remote workers with MA primary worksite.',
    notes:'Very recently effective (10/29/2025). EEO reporting data may also be required.',
  },
  'MN': {
    state:'Minnesota', effectiveDate:'01/01/2025', citation:'CHAPTER 110 — S.F. No. 3852, Article 7',
    employerThreshold:'30+ employees at one or more MN work sites',
    wagReq:'Starting salary range or fixed pay rate (no open-ended ranges). General description of all benefits and other compensation including health and retirement.',
    postingReq:'Any solicitation intended to recruit applicants, electronic or printed, that includes qualifications.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Not specified.',
    notes:'Benefits description required.',
  },
  'NJ': {
    state:'New Jersey', effectiveDate:'06/01/2025', citation:'P.L. 2024, c. 91',
    employerThreshold:'10+ employees over 20 calendar weeks. Applies to employers doing business in NJ, employing people in NJ, or taking applications from NJ residents.',
    wagReq:'Hourly wage or salary, or range. General description of benefits and other compensation for first 12 months. Vague language like "great benefits offered" or "health insurance and more" not permitted.',
    postingReq:'All job postings, promotions, new jobs, and transfers, internal and external.',
    benefitsReq:true,
    longArm:true, longArmNote:'Applies to out-of-state employers incorporated/headquartered in NJ, with NJ employees, NJ contracts/sales, or NJ applicants.',
    remoteCoverage:'Covered if employer takes applications from NJ residents.',
    notes:'Very recently effective (06/01/2025). Long-arm reach for out-of-state employers.',
  },
  'NY': {
    state:'New York', effectiveDate:'09/17/2023', citation:'N.Y. Lab. Law § 194-b',
    employerThreshold:'4+ employees (not required to be in NY)',
    wagReq:'Actual compensation or min/max annual or hourly range. Excludes benefits and bonuses. Good-faith basis at time of posting.',
    postingReq:'Each single new job, promotion, or transfer opportunity, per location.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'Remote jobs outside NY where worker reports to a NY supervisor, officer, or work site.',
    notes:'Lowest employee threshold (4+) among covered states.',
  },
  'VT': {
    state:'Vermont', effectiveDate:'07/01/2025', citation:'Act 155 (H.704)',
    employerThreshold:'5+ employees, at least one of whom works in Vermont',
    wagReq:'Min/max annual salary or hourly range (good-faith expectation). Commission-based jobs must state that range cannot be posted. Tipped jobs must disclose base wage.',
    postingReq:'Any written notice in any format for a specific job opening.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'Remote positions predominantly performing work for a VT-based office or location.',
    notes:'Recently effective (07/01/2025). Employer may hire outside posted range due to applicant qualifications or market factors.',
  },
  'DC': {
    state:'Washington, D.C.', effectiveDate:'06/20/2024', citation:'D.C. Act 25-367; Wage Transparency Omnibus Amendment Act of 2023',
    employerThreshold:'1+ employee in DC (excludes DC/Federal Government as employer)',
    wagReq:'Min/max projected salary or hourly pay. Good-faith range from lowest to highest the employer believes it would pay.',
    postingReq:'All job listings and position descriptions advertised, regardless of how or where created/shared.',
    benefitsReq:false,
    longArm:false,
    remoteCoverage:'All postings soliciting DC employees.',
    notes:'Very broad coverage — applies to any posting soliciting DC workers, any size employer.',
  },
  'WA': {
    state:'Washington State', effectiveDate:'01/01/2023', citation:'RCW 49.58.110; Amended SSB 5408',
    employerThreshold:'15+ employees, with at least 1 WA-based employee',
    wagReq:'Opening wage scale or salary range (or fixed wage if no range). Min/max without open-ended phrases. General description of all benefits and other compensation.',
    postingReq:'Job postings for new jobs, promotions, or transfers. Any written medium (print or electronic), managed by employer or third party.',
    benefitsReq:true,
    longArm:false,
    remoteCoverage:'Any position that could be filled by a WA-based employee, including remote work. No disclosure needed for jobs performed entirely outside WA.',
    notes:'Benefits description required. If no existing range, create one before publishing.',
  },
};

// State abbreviation aliases (DC needs special handling)

export const EPT_STATE_ALIASES = {
  'WASHINGTON DC':'DC','WASHINGTON D.C.':'DC','D.C.':'DC',
  'DISTRICT OF COLUMBIA':'DC','CALIFORNIA':'CA','COLORADO':'CO',
  'HAWAII':'HI','ILLINOIS':'IL','MARYLAND':'MD','MASSACHUSETTS':'MA',
  'MINNESOTA':'MN','NEW JERSEY':'NJ','NEW YORK':'NY','VERMONT':'VT',
  'WASHINGTON':'WA','WASHINGTON STATE':'WA',
};

export function lookupEpt(stateVal, city) {
  if (!stateVal) return null;
  const s = stateVal.trim().toUpperCase();
  // Try 2-letter code first
  if (EPT_DATA[s]) return EPT_DATA[s];
  // Try alias
  const aliased = EPT_STATE_ALIASES[s];
  if (aliased && EPT_DATA[aliased]) return EPT_DATA[aliased];
  // Special case: Washington could be state or DC
  if (s === 'WA' || s === 'WASHINGTON STATE') return EPT_DATA['WA'];
  if (city && /washington.*d\.?c\.?|district.*columbia/i.test(city)) return EPT_DATA['DC'];
  return null;
}

export function EptCard({ stateVal, city, telecommute, wageFrom, wageTo }) {
  const ept = lookupEpt(stateVal, city);

  const hasRange = wageFrom && wageTo && wageFrom.trim() && wageTo.trim();

  if (!stateVal || !stateVal.trim()) {
    return (
      <div style={{...PS.card, marginBottom:20, opacity:0.5}}>
        {cardHeaderStatic('Equal Pay Transparency', 'EPT Wage Posting Requirements', null)}
        <div style={{fontSize:12, color:'var(--text3)', fontStyle:'italic'}}>Enter a state in Case Inputs to check EPT requirements.</div>
      </div>
    );
  }

  if (!ept) {
    return (
      <div style={{...PS.card, marginBottom:20}}>
        {cardHeaderStatic('Equal Pay Transparency', 'EPT Wage Posting Requirements', true)}
        <div style={{fontSize:12, color:'var(--text2)'}}>
          <span style={{color:'var(--green)', fontWeight:600}}>No EPT law on record</span> for <strong>{stateVal}</strong> based on AILA's October 2025 guide. Verify independently — laws are frequently updated.
        </div>
      </div>
    );
  }

  const rangeFlag = ept && hasRange ? null : (ept ? false : null);

  return (
    <div style={{...PS.card, marginBottom:20}}>
      {cardHeaderStatic('Equal Pay Transparency', `EPT Requirements — ${ept.state}`, hasRange ? true : null)}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:14}}>
        <div>
          <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Effective Date</div>
          <div style={{fontSize:13, color:'var(--text)'}}>{ept.effectiveDate}</div>
        </div>
        <div>
          <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Covered Employers</div>
          <div style={{fontSize:13, color:'var(--text)'}}>{ept.employerThreshold}</div>
        </div>
      </div>

      <div style={{display:'grid', gap:10, marginBottom:14}}>
        <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--bg3)', border:'1px solid var(--border)'}}>
          <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Posting Requirement</div>
          <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.postingReq}</div>
        </div>
        <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background: hasRange?'var(--green-dim)':'var(--amber-dim)', border:`1px solid ${hasRange?'#34d39944':'#f59e0b44'}`}}>
          <div style={{fontSize:10, fontWeight:600, color: hasRange?'var(--green)':'var(--amber)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>
            Wage Range Requirement {hasRange ? '✓ Range entered' : '⚠ No range entered yet'}
          </div>
          <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.wagReq}</div>
        </div>
        {ept.benefitsReq && (
          <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--amber-dim)', border:'1px solid #f59e0b44'}}>
            <div style={{fontSize:10, fontWeight:600, color:'var(--amber)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>⚠ Benefits Description Required</div>
            <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>This state requires a general description of benefits and other compensation in job postings, not just a wage range.</div>
          </div>
        )}
        {ept.longArm && (
          <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--red-dim)', border:'1px solid #f8717144'}}>
            <div style={{fontSize:10, fontWeight:600, color:'var(--red)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>⚠ Long-Arm Reach</div>
            <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.longArmNote}</div>
          </div>
        )}
        {telecommute === 'yes' && ept.remoteCoverage && (
          <div style={{padding:'10px 12px', borderRadius:'var(--radius)', background:'var(--bg3)', border:'1px solid var(--border)'}}>
            <div style={{fontSize:10, fontWeight:600, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.08em', marginBottom:4}}>Remote / WFH Coverage</div>
            <div style={{fontSize:12, color:'var(--text2)', lineHeight:1.6}}>{ept.remoteCoverage}</div>
          </div>
        )}
        {ept.notes && (
          <div style={{fontSize:11, color:'var(--text3)', fontStyle:'italic', paddingTop:4}}>{ept.notes}</div>
        )}
      </div>
      <div style={{fontSize:10, color:'var(--text3)', borderTop:'1px solid var(--border)', paddingTop:10}}>
        Source: AILA Practice Pointer — Guide to Equal Pay Transparency Laws (Oct 2025), Doc. No. 25110603. Laws change frequently — verify with local employment counsel before recruitment.
      </div>
    </div>
  );
}

// Standalone cardHeader used outside PermComparer (no closure over local vars)

export function cardHeaderStatic(kicker, title, match) {
  return (
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
      <div>
        <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>{kicker}</div>
        <div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>{title}</div>
      </div>
      <span style={{display:'inline-flex',alignItems:'center',gap:5,fontSize:11,fontWeight:500,padding:'3px 8px',borderRadius:4,
        background: match===null?'var(--bg4)':match?'var(--green-dim)':'var(--red-dim)',
        color: match===null?'var(--text2)':match?'var(--green)':'var(--red)',
      }}>
        {match===null?'Not Checked':match?'Law in Effect — Compliant':'Law in Effect'}
      </span>
    </div>
  );
}

// ── Recruitment Compliance Audit (mode 2 of the PERM Comparer) ───────────────
// Tests each recruitment piece against the PWD using the deterministic engine in
// permCompliance.js (grounded in 20 CFR 656 + BALCA). See
// docs/perm-recruitment-comparer-analysis.json.

export const AUDIT_STATUS = {
  pass:   { bg:'var(--green-dim)', fg:'var(--green)', label:'Pass'   },
  fail:   { bg:'var(--red-dim)',   fg:'var(--red)',   label:'Fail'   },
  flag:   { bg:'var(--amber-dim)', fg:'var(--amber)', label:'Flag'   },
  review: { bg:'var(--bg4)',       fg:'var(--text2)', label:'Review' },
  na:     { bg:'var(--bg4)',       fg:'var(--text3)', label:'N/A'    },
};

export const VERDICT = {
  compliant:            { bg:'var(--green-dim)', fg:'var(--green)', label:'Compliant' },
  compliant_with_flags: { bg:'var(--amber-dim)', fg:'var(--amber)', label:'Compliant — items to verify' },
  defective:            { bg:'var(--red-dim)',   fg:'var(--red)',   label:'Defective' },
};

export function AuditStatusPill({status}){
  const s=AUDIT_STATUS[status]||AUDIT_STATUS.review;
  return <span style={{display:'inline-flex',alignItems:'center',borderRadius:999,padding:'2px 9px',fontSize:10,fontWeight:600,background:s.bg,color:s.fg,whiteSpace:'nowrap'}}>{s.label}</span>;
}

// Drag-and-drop zone for the reference PWD (ETA-9141) in Recruitment Review mode.

export function PwdDropZone({onPwdDrop,loading,pwd}){
  const [dragging,setDragging]=useState(false);
  const [err,setErr]=useState('');
  const fileRef=useRef(null);
  const handle=async(file)=>{
    if(!file)return;
    if(file.type!=='application/pdf'){setErr('Please drop a PDF of the ETA-9141.');return;}
    setErr('');
    try{ await onPwdDrop(file); }catch(e){ setErr('Extraction failed: '+e.message); }
    if(fileRef.current)fileRef.current.value='';
  };
  const havePwd=!!(pwd.jobTitle||pwd.city||pwd.pwdWage);
  return (
    <div
      onClick={()=>fileRef.current?.click()}
      onDragOver={e=>{e.preventDefault();setDragging(true);}}
      onDragLeave={()=>setDragging(false)}
      onDrop={e=>{e.preventDefault();setDragging(false);handle(e.dataTransfer.files[0]);}}
      style={{cursor:'pointer',borderRadius:'var(--radius-lg)',border:`1.5px dashed ${dragging?'var(--amber)':'var(--border2)'}`,background:dragging?'var(--amber-dim)':'var(--bg)',padding:'18px 16px',textAlign:'center',transition:'all .15s'}}>
      {loading?(
        <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:8,color:'var(--text2)',fontSize:12}}>
          <div style={{width:12,height:12,border:'2px solid var(--amber)',borderTopColor:'transparent',borderRadius:'50%',animation:'spin .7s linear infinite'}}/> Extracting PWD…
        </div>
      ):havePwd?(
        <div style={{fontSize:12,color:'var(--text2)'}}>
          <div style={{fontWeight:600,color:'var(--text)',marginBottom:3}}>{pwd.jobTitle||'(no title)'}</div>
          {pwd.city}{pwd.stateVal?`, ${pwd.stateVal}`:''} · {pwd.pwdWage||'(no wage)'}{pwd.socCode?` · SOC ${pwd.socCode}`:''}{pwd.pwdExpirationDate?` · valid to ${pwd.pwdExpirationDate}`:''}
          <div style={{fontSize:11,color:'var(--text3)',marginTop:4}}>Drop a different ETA-9141 PDF to replace</div>
        </div>
      ):(
        <div style={{fontSize:12.5,color:'var(--text3)'}}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" style={{marginBottom:6,opacity:.7}}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <div style={{fontWeight:600,color:'var(--text2)'}}>Drag &amp; drop the Prevailing Wage Determination (ETA-9141 PDF)</div>
          <div style={{marginTop:3}}>or click to browse — fields populate automatically</div>
        </div>
      )}
      {err&&<div style={{marginTop:8,fontSize:11,color:'var(--red)'}}>{err}</div>}
      <input ref={fileRef} type="file" accept="application/pdf" style={{display:'none'}} onChange={e=>handle(e.target.files[0])}/>
    </div>
  );
}

export function RecruitmentPieceCard({piece,pwd,refText,onChange,onRemove}){
  const [showDiff,setShowDiff]=useState(false);
  const meta=RECRUITMENT_TYPES[piece.type]||RECRUITMENT_TYPES.newspaper_general;
  const audit=piece.rawText.trim()?auditRecruitmentPiece(pwd,piece):null;
  const v=audit?VERDICT[audit.overallVerdict]:null;
  // Visual comparison: recruitment text vs the PWD job description + minimum
  // requirements (formatting ignored, to focus on substantive differences).
  const diffRes=(piece.rawText.trim()&&(refText||'').trim())
    ? pSummarize('Recruitment vs PWD',refText,piece.rawText,false,true) : null;
  const dateInput=(label,key)=>(
    <div><label style={{...PS.label,fontSize:10}}>{label}</label>
      <input type="date" style={{...PS.input,fontSize:11,padding:'6px 8px'}} value={piece[key]||''} onChange={e=>onChange({[key]:e.target.value})}/></div>
  );
  return (
    <div style={{...PS.card,marginBottom:16}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:12,marginBottom:12}}>
        <select value={piece.type} onChange={e=>onChange({type:e.target.value})}
          style={{...PS.input,width:'auto',flex:'0 1 460px',fontSize:12,fontWeight:600}}>
          {[...new Set(Object.values(RECRUITMENT_TYPES).map(m=>m.group))].map(group=>(
            <optgroup key={group} label={group}>
              {Object.entries(RECRUITMENT_TYPES).filter(([,m])=>m.group===group).map(([k,m])=>(
                <option key={k} value={k}>{m.label}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          {v&&<span style={{display:'inline-flex',alignItems:'center',borderRadius:999,padding:'4px 12px',fontSize:11,fontWeight:600,background:v.bg,color:v.fg}}>{v.label}</span>}
          <button onClick={onRemove} title="Remove" style={{fontSize:11,padding:'4px 10px',background:'var(--bg3)',color:'var(--text3)',border:'1px solid var(--border)',borderRadius:8,cursor:'pointer'}}>Remove</button>
        </div>
      </div>
      <DropTextarea value={piece.rawText} onChange={e=>onChange({rawText:e.target.value})} minHeight={120} acceptDocx
        placeholder="Paste the recruitment text (ad, notice, posting), or drag a document (Word .docx or PDF) to extract…"/>
      {/* Date / wage inputs that feed the deterministic checks */}
      <div style={{display:'grid',gridTemplateColumns:meta.isNof?'1fr 1fr 1fr 1fr':'1fr 1fr',gap:10,marginTop:12}}>
        {meta.isNof
          ? <>{dateInput('Date posted','postedDate')}{dateInput('Date removed','removedDate')}{dateInput('9089 filing date','filingDate')}{dateInput('Offered wage ($)','offeredWage')}</>
          : <>{dateInput('Publication date','pubDate')}
              <div><label style={{...PS.label,fontSize:10}}>Offered wage to alien ($, optional)</label>
                <input style={{...PS.input,fontSize:11,padding:'6px 8px'}} placeholder="$0" value={piece.offeredWage||''} onChange={e=>onChange({offeredWage:e.target.value})}/></div></>}
      </div>
      {audit&&(
        <div style={{marginTop:14,display:'grid',gap:6}}>
          {audit.findings.map((f,i)=>(
            <div key={i} style={{display:'grid',gridTemplateColumns:'80px 1fr',gap:10,alignItems:'start',padding:'8px 10px',borderRadius:8,background:'var(--bg3)'}}>
              <AuditStatusPill status={f.status}/>
              <div style={{minWidth:0}}>
                <div style={{fontSize:12,color:'var(--text)',fontWeight:600}}>{f.title}</div>
                <div style={{fontSize:11.5,color:'var(--text2)',lineHeight:1.5,marginTop:2}}>{f.detail}</div>
                {f.citation&&<div style={{fontSize:10,color:'var(--text3)',marginTop:3,fontFamily:"'DM Mono',monospace"}}>{f.citation}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
      {diffRes&&(
        <div style={{marginTop:14}}>
          <button onClick={()=>setShowDiff(s=>!s)}
            style={{fontSize:11,padding:'5px 12px',background:'var(--bg3)',color:'var(--text2)',border:'1px solid var(--border)',borderRadius:8,cursor:'pointer',display:'inline-flex',alignItems:'center',gap:6}}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{transform:showDiff?'rotate(90deg)':'none',transition:'transform .15s'}}><polyline points="9 18 15 12 9 6"/></svg>
            {showDiff?'Hide':'Show'} visual comparison vs PWD
            {!diffRes.exact&&<span style={{color:'var(--amber)'}}>· {diffRes.detail}</span>}
          </button>
          {showDiff&&<div style={{marginTop:12}}><PermDiffPanel res={diffRes} title="Recruitment vs PWD (Job Description + Minimum Requirements)"/></div>}
        </div>
      )}
    </div>
  );
}

export function RecruitmentAuditPanel({pwd,refText}){
  const [pieces,setPieces]=useState([
    {id:1,type:'newspaper_general',rawText:'',pubDate:'',postedDate:'',removedDate:'',filingDate:'',offeredWage:''},
  ]);
  const upd=(id,patch)=>setPieces(p=>p.map(x=>x.id===id?{...x,...patch}:x));
  const add=()=>setPieces(p=>[...p,{id:(p.reduce((m,x)=>Math.max(m,x.id),0)+1),type:'job_search_website',rawText:'',pubDate:'',postedDate:'',removedDate:'',filingDate:'',offeredWage:''}]);
  const rm=(id)=>setPieces(p=>p.length>1?p.filter(x=>x.id!==id):p);
  return (
    <div style={{display:'grid',gap:16,marginBottom:20}}>
      <div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>Recruitment Pieces</div>
      {pieces.map(pc=>(
        <RecruitmentPieceCard key={pc.id} piece={pc} pwd={pwd} refText={refText}
          onChange={patch=>upd(pc.id,patch)} onRemove={()=>rm(pc.id)}/>
      ))}
      <button onClick={add} className="primary" style={{fontSize:12,padding:'9px 16px',justifySelf:'start'}}>+ Add recruitment piece</button>
    </div>
  );
}

export function PermComparer(){
  const [mode,setMode]=useState('diff'); // 'diff' | 'audit'
  const [auditKey,setAuditKey]=useState(0); // bump to reset the recruitment-pieces panel
  const [pwdData,setPwdData]=useState({}); // full extracted ETA-9141 dict (for the audit engine)
  const [jobTitle,setJobTitle]=useState('');
  const [city,setCity]=useState('');
  const [stateVal,setStateVal]=useState('');
  const [telecommute,setTelecommute]=useState('no');
  const [telecommuteText,setTelecommuteText]=useState('');
  const [jdRef,setJdRef]=useState('');
  const [jdCmp,setJdCmp]=useState('');
  const [mrRef,setMrRef]=useState('');
  const [mrCmp,setMrCmp]=useState('');
  const [primDeg,setPrimDeg]=useState('');
  const [secDeg,setSecDeg]=useState('');
  const [travel,setTravel]=useState('');
  const [strict,setStrict]=useState(false);
  const [ignoreFmt,setIgnoreFmt]=useState(false);
  const [pwdWage,setPwdWage]=useState('');
  const [wageFrom,setWageFrom]=useState('');
  const [wageTo,setWageTo]=useState('');
  const [results,setResults]=useState(null);
  const [expLetters,setExpLetters]=useState([]);
  const [showExpModal,setShowExpModal]=useState(false);
  const [droppedLetter,setDroppedLetter]=useState(null);

  const compare=()=>setResults({
    jd:pSummarize('Job Description',jdRef,jdCmp,strict,ignoreFmt),
    mr:pSummarize('Minimum Requirements',mrRef,mrCmp,strict,ignoreFmt),
  });
  const [pwdLoading,setPwdLoading]=useState(false);
  const [pwdError,setPwdError]=useState('');
  const pwdInputRef=useRef(null);

  const handleSaveLetter=(letter,idx)=>{
    if(idx===null||idx===undefined){
      setExpLetters(prev=>[...prev,letter]);
    } else {
      setExpLetters(prev=>prev.map((l,i)=>i===idx?letter:l));
    }
  };
  const handleRemoveLetter=(idx)=>setExpLetters(prev=>prev.filter((_,i)=>i!==idx));
  const savedMonths=expLetters.filter(l=>l.saved).reduce((s,l)=>s+(l.months||0),0);

  // Drop a PWD into the Reference box → same as Load PWD button
  const handlePwdDrop = async (file) => {
    setPwdLoading(true); setPwdError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/extract-pwd', { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Server error' }));
        throw new Error(err.detail || 'Extraction failed');
      }
      const d = await resp.json();
      setPwdData(d);
      if (d.jobTitle) setJobTitle(d.jobTitle);
      if (d.city)     setCity(d.city);
      if (d.stateVal) setStateVal(d.stateVal);
      setTelecommute(d.telecommuteDetail ? 'yes' : (d.travel === 'yes' ? 'yes' : 'no'));
      setTelecommuteText(d.telecommuteDetail || '');
      setTravel(d.travelDetail || '');
      if (d.jdRef)   setJdRef(d.jdRef);
      if (d.primDeg) setPrimDeg(d.primDeg);
      if (d.mrRef)   setMrRef(d.mrRef);
      if (d.pwdWage) setPwdWage(d.pwdWage);
    } catch(e) {
      setPwdError('Could not extract PWD: ' + e.message);
    } finally {
      setPwdLoading(false);
    }
  };

  // Drop an experience letter into the Comparison box → parse & store it,
  // put duties text in the box, pre-load it into the modal
  const handleLetterDrop = async (file) => {
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/extract-experience-letter', { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Server error' }));
        throw new Error(err.detail || 'Extraction failed');
      }
      const parsed = await resp.json();
      const letterObj = { fileName: file.name, ...parsed, saved: false };
      setDroppedLetter(letterObj);
      // Populate the comparison textarea with the letter's duties / full text
      setJdCmp(parsed.duties || parsed.fullText || '');
    } catch(e) {
      throw e; // DropTextarea will surface the error
    }
  };

  const clearAll=()=>{setJobTitle('');setCity('');setStateVal('');setTelecommute('no');setTelecommuteText('');setJdRef('');setJdCmp('');setMrRef('');setMrCmp('');setPrimDeg('');setSecDeg('');setTravel('');setPwdWage('');setWageFrom('');setWageTo('');setResults(null);setPwdError('');setExpLetters([]);setShowExpModal(false);setDroppedLetter(null);setPwdData({});setAuditKey(k=>k+1);};

  const loadPwd=async(file)=>{
    if(!file)return;
    setPwdLoading(true);setPwdError('');
    try{
      const fd=new FormData();
      fd.append('file',file);
      const resp=await fetch('/api/extract-pwd',{method:'POST',body:fd});
      if(!resp.ok){
        const err=await resp.json().catch(()=>({detail:'Server error'}));
        throw new Error(err.detail||'Extraction failed');
      }
      const d=await resp.json();
      setPwdData(d);
      if(d.jobTitle)setJobTitle(d.jobTitle);
      if(d.city)setCity(d.city);
      if(d.stateVal)setStateVal(d.stateVal);
      setTelecommute(d.telecommuteDetail?'yes':(d.travel==='yes'?'yes':'no'));
      setTelecommuteText(d.telecommuteDetail||'');
      setTravel(d.travelDetail||'');
      if(d.jdRef)setJdRef(d.jdRef);
      if(d.primDeg)setPrimDeg(d.primDeg);
      if(d.mrRef)setMrRef(d.mrRef);
      if(d.pwdWage)setPwdWage(d.pwdWage);
    }catch(e){
      setPwdError('Could not extract fields: '+e.message);
    }finally{
      setPwdLoading(false);
      if(pwdInputRef.current)pwdInputRef.current.value='';
    }
  };

  const wageStatus=(()=>{
    const pwd=pParseCur(pwdWage),from=pParseCur(wageFrom),to=pParseCur(wageTo);
    if(pwd===null||from===null||!wageFrom.trim())return{status:'Needs Input',detail:'Enter PWD wage and From wage to validate.',pass:false};
    // A wage (or the bottom of an advertised range) that is AT OR ABOVE the prevailing
    // wage is compliant: the offered wage must "equal or exceed" the PWD (20 CFR 656.10(c)(1)),
    // and an advertised range whose floor is no less than the PWD is permissible
    // (20 CFR 656.17(f)(5); Credit Suisse Securities (USA) LLC, 2010-PER-00103).
    if(from>=pwd)return{status:'Pass',detail:to!==null?`Range ${pFmt(wageFrom)}–${pFmt(wageTo)} starts at or above PWD ${pFmt(pwdWage)}.`:`From wage ${pFmt(wageFrom)} is at or above PWD ${pFmt(pwdWage)}.`,pass:true};
    return{status:'Flag',detail:`From wage ${pFmt(wageFrom)} is below PWD ${pFmt(pwdWage)} — must be at or above it.`,pass:false};
  })();

  const pillBtn=(label,active,onClick)=>(
    <button onClick={onClick} style={{fontSize:11,padding:'3px 10px',height:'auto',background:active?'var(--amber-dim)':'var(--bg3)',color:active?'var(--amber)':'var(--text3)',border:active?'1px solid #f59e0b44':'1px solid var(--border)',borderRadius:20,fontWeight:active?500:400,cursor:'pointer'}}>{label}</button>
  );

  const grid2={display:'grid',gridTemplateColumns:'1fr 1fr',gap:20,alignItems:'start'};
  const grid3={display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:16};
  const cardHeader=(kicker,title,match)=>(
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
      <div><div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>{kicker}</div><div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>{title}</div></div>
      <span style={PS.badge(match)}>{match===null?'Source Text':match?'Exact Match':'Differences Found'}</span>
    </div>
  );

  // PWD reference for the audit engine: the full extracted dict, with the
  // user-editable fields (which may have been corrected on screen) taking
  // precedence over the raw extraction.
  const pwdForAudit={
    ...pwdData,
    jobTitle, city, stateVal,
    pwdWage, pwdWageNum:pParseCur(pwdWage),
    travel: (travel&&travel.trim())?'yes':(pwdData.travel||'no'),
    travelDetail: travel, telecommuteDetail: telecommuteText,
    employerName: pwdData.employerName||'',
    jdRef, mrRef,
    primDegLevel: primDeg||pwdData.primDegLevel||'',
  };
  // Reference text shown/diffed in Recruitment Review (PWD job description + minimum requirements).
  const auditRefText=[jdRef,mrRef].filter(s=>s&&s.trim()).join('\n\n');

  return(
    <>
    <div style={{height:'100%',overflowY:'auto',padding:'32px 28px 48px',background:'var(--bg)'}}>
      <div style={{maxWidth:1360,margin:'0 auto'}}>

        {/* Hero */}
        <div style={{display:'flex',alignItems:'flex-end',justifyContent:'space-between',gap:24,marginBottom:24}}>
          <div>
            <div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:6}}>PERM Labor Certification</div>
            <div style={{fontFamily:"'DM Serif Display',serif",fontSize:'clamp(1.6rem,3vw,2.4rem)',color:'var(--text)',lineHeight:1.1}}>{mode==='audit'?'Recruitment Compliance Review':'Text Comparison Workspace'}</div>
            <div style={{fontSize:13,color:'var(--text3)',marginTop:8,maxWidth:600,lineHeight:1.6}}>{mode==='audit'?'Test each recruitment piece against the PWD under 20 CFR 656 and BALCA — wage floor, geographic area, requirements-not-exceeding-9089, and Notice-of-Filing content.':'Compare job description and requirements language, validate PWD wage positioning.'}</div>
          </div>
          <div style={{display:'flex',flexWrap:'wrap',justifyContent:'flex-end',gap:10,alignItems:'center',flexShrink:0}}>
            <div style={{display:'flex',gap:0,border:'1px solid var(--border)',borderRadius:20,overflow:'hidden'}}>
              {[['diff','Text Diff'],['audit','Recruitment Review']].map(([m,lbl])=>(
                <button key={m} onClick={()=>setMode(m)} style={{fontSize:11,padding:'5px 14px',border:'none',cursor:'pointer',background:mode===m?'var(--amber-dim)':'transparent',color:mode===m?'var(--amber)':'var(--text3)',fontWeight:mode===m?600:400}}>{lbl}</button>
              ))}
            </div>
            {mode==='diff'&&pillBtn('Ignore Formatting',ignoreFmt,()=>setIgnoreFmt(v=>!v))}
            {mode==='diff'&&pillBtn('Strict Mode',strict,()=>setStrict(v=>!v))}
            <input ref={pwdInputRef} type="file" accept="application/pdf" style={{display:'none'}} onChange={e=>loadPwd(e.target.files[0])}/>
          <button onClick={()=>pwdInputRef.current?.click()} disabled={pwdLoading} style={{fontSize:11,padding:'5px 14px',height:'auto',display:'flex',alignItems:'center',gap:6,background:pwdLoading?'var(--bg3)':'var(--green-dim)',color:pwdLoading?'var(--text3)':'var(--green)',border:pwdLoading?'1px solid var(--border)':'1px solid #34d39944',borderRadius:20,cursor:pwdLoading?'default':'pointer',opacity:pwdLoading?0.6:1}}>
            {pwdLoading?<><div style={{width:10,height:10,border:'1.5px solid currentColor',borderTopColor:'transparent',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>{' Extracting…'}</>:<><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>{' Load PWD'}</>}
          </button>
          {mode==='diff'&&<button onClick={()=>{
            if(droppedLetter&&!expLetters.find(l=>l.fileName===droppedLetter.fileName)){
              setExpLetters(prev=>[...prev,droppedLetter]);
            }
            setShowExpModal(true);
          }} style={{fontSize:11,padding:'5px 14px',height:'auto',display:'flex',alignItems:'center',gap:6,background:'var(--bg3)',color:(expLetters.length>0||droppedLetter)?'var(--amber)':'var(--text2)',border:(expLetters.length>0||droppedLetter)?'1px solid #f59e0b44':'1px solid var(--border)',borderRadius:20,cursor:'pointer'}}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            {' Verify Experience'}{expLetters.length>0&&<span style={{marginLeft:4,padding:'1px 6px',background:'var(--amber)',color:'var(--bg)',borderRadius:10,fontSize:10,fontWeight:700}}>{expLetters.length}</span>}
          </button>}
          <button onClick={clearAll} style={{fontSize:11,padding:'5px 14px',height:'auto',background:'var(--bg3)',color:'var(--text3)',border:'1px solid var(--border)',borderRadius:20,cursor:'pointer'}}>Clear All</button>
            {mode==='diff'&&<button onClick={compare} className="primary" style={{fontSize:12,padding:'7px 18px'}}>Compare Text</button>}
          </div>
        </div>
        {pwdError&&<div style={{margin:'0 0 16px',padding:'10px 14px',background:'var(--red-dim)',color:'var(--red)',borderRadius:'var(--radius)',fontSize:12}}>{pwdError}</div>}

        {/* Case metadata */}
        <div style={{...PS.card,marginBottom:20}}>
          {cardHeader('Case Inputs','Location & Telecommute',null)}
          <div style={{marginBottom:14}}><label style={PS.label}>Job Title</label><input style={PS.input} value={jobTitle} onChange={e=>setJobTitle(e.target.value)}/></div>
          <div style={{...grid2,marginBottom:14}}>
            <div><label style={PS.label}>City</label><input style={PS.input} value={city} onChange={e=>setCity(e.target.value)}/></div>
            <div><label style={PS.label}>State</label><input style={PS.input} value={stateVal} onChange={e=>setStateVal(e.target.value)}/></div>
          </div>
          <div style={{...grid2}}>
            <div><label style={PS.label}>Telecommute Language</label><textarea style={{...PS.textarea,minHeight:60}} value={telecommuteText} placeholder="Populated from the PWD…" onChange={e=>{setTelecommuteText(e.target.value);setTelecommute(e.target.value.trim()?'yes':'no');}}/></div>
            <div><label style={PS.label}>Travel Requirement</label><textarea style={{...PS.textarea,minHeight:60}} value={travel} placeholder="Populated from the PWD…" onChange={e=>setTravel(e.target.value)}/></div>
          </div>
        </div>

        {mode==='audit' && <>
          <div style={{...PS.card,marginBottom:20}}>
            {cardHeader('Reference PWD','What we pulled from the ETA-9141',null)}
            <PwdDropZone onPwdDrop={handlePwdDrop} loading={pwdLoading} pwd={pwdForAudit}/>
            <div style={{...grid3,margin:'16px 0 14px'}}>
              <div><label style={PS.label}>PWD Wage</label><input style={PS.input} placeholder="$0.00 / Year" value={pwdWage} onChange={e=>setPwdWage(e.target.value)}/></div>
              <div><label style={PS.label}>Primary Degree</label><input style={PS.input} placeholder="e.g. Bachelor's" value={primDeg} onChange={e=>setPrimDeg(e.target.value)}/></div>
              <div><label style={PS.label}>Min Experience (months)</label><input style={PS.input} placeholder="e.g. 72" value={pwdData.primExpMonths??''} onChange={e=>{const n=e.target.value.replace(/[^\d]/g,'');setPwdData(d=>({...d,primExpMonths:n===''?null:Number(n)}));}}/></div>
            </div>
            {pwdData.pwdWageMin!=null && pwdData.pwdWageAlt!=null && pwdData.pwdWageMin!==pwdData.pwdWageAlt && (
              <div style={{margin:'-4px 0 14px',padding:'10px 12px',borderRadius:'var(--radius)',background:'var(--amber-dim)',color:'var(--amber)',fontSize:11.5,lineHeight:1.5}}>
                This PWD lists two prevailing wages — minimum requirements <strong>{pFmt(pwdData.pwdWageMin)}</strong> and alternative requirements <strong>{pFmt(pwdData.pwdWageAlt)}</strong>. Using the higher (<strong>{pFmt(Math.max(pwdData.pwdWageMin,pwdData.pwdWageAlt))}</strong>) as the wage floor.
              </div>
            )}
            <div style={{marginBottom:14}}><label style={PS.label}>Job Description (from PWD — editable)</label>
              <textarea style={{...PS.textarea,minHeight:120}} value={jdRef} placeholder="Drop the PWD above to populate, or paste the job duties…" onChange={e=>setJdRef(e.target.value)}/></div>
            <div><label style={PS.label}>Minimum Requirements (from PWD — editable)</label>
              <textarea style={{...PS.textarea,minHeight:160}} value={mrRef} placeholder="Drop the PWD above to populate, or paste the minimum requirements…" onChange={e=>setMrRef(e.target.value)}/></div>
          </div>
          <RecruitmentAuditPanel key={auditKey} pwd={pwdForAudit} refText={auditRefText}/>
        </>}

        {mode==='diff' && <>
        {/* Job Description pair */}
        <div style={{display:'grid',gap:16,marginBottom:20}}>
          <div style={grid2}>
            <div style={PS.cardRef}>
              {cardHeader('Reference','Job Description',null)}
              <label style={PS.label}>Paste the official job description, or drag and drop the PWD (PDF) — fields will populate automatically</label>
              <DropTextarea
                value={jdRef}
                onChange={e=>setJdRef(e.target.value)}
                placeholder="Paste job description text here, or drag and drop a PWD PDF to populate all fields automatically…"
                onPwdDrop={handlePwdDrop}
              />
            </div>
            <div style={PS.card}>
              {cardHeader('Comparison','Job Description Comparison',results?results.jd.exact:null)}
              <label style={PS.label}>Paste comparison text, or drag and drop an experience verification letter (PDF) — then click Verify Experience to check requirements</label>
              <DropTextarea
                value={jdCmp}
                onChange={e=>setJdCmp(e.target.value)}
                placeholder="Paste comparison text here, or drag and drop an experience verification letter PDF…"
                onLetterDrop={handleLetterDrop}
                borderColor={results&&!results.jd.exact?'var(--red)':'var(--border)'}
                background={results&&!results.jd.exact?'var(--red-dim)':'var(--bg)'}
              />
            </div>
          </div>
          {results&&<PermDiffPanel res={results.jd} title="Job Description"/>}
        </div>

        {/* Min Requirements pair */}
        <div style={{display:'grid',gap:16,marginBottom:20}}>
          <div style={grid2}>
            <div style={PS.cardRef}>
              {cardHeader('Reference','Minimum Requirements',null)}
              <div style={{display:'grid',gap:12,marginBottom:14}}>
                <div><label style={PS.label}>Primary Degree</label><textarea style={{...PS.textarea,minHeight:70}} value={primDeg} onChange={e=>setPrimDeg(e.target.value)}/></div>
                <div><label style={PS.label}>Secondary Degree (if any)</label><textarea style={{...PS.textarea,minHeight:70}} value={secDeg} onChange={e=>setSecDeg(e.target.value)}/></div>
              </div>
              <label style={PS.label}>Paste the minimum requirements</label>
              <textarea style={{...PS.textarea,minHeight:260}} value={mrRef} onChange={e=>setMrRef(e.target.value)}/>
            </div>
            <div style={PS.card}>
              {cardHeader('Comparison','Requirements Comparison',results?results.mr.exact:null)}
              <label style={PS.label}>Text to compare against</label>
              <textarea style={{...PS.textarea,minHeight:260,borderColor:results&&!results.mr.exact?'var(--amber)':'var(--border)',background:results&&!results.mr.exact?'var(--amber-dim)':'var(--bg)'}} value={mrCmp} onChange={e=>setMrCmp(e.target.value)}/>
            </div>
          </div>
          {results&&<PermDiffPanel res={results.mr} title="Minimum Requirements"/>}
        </div>

        {/* Wage check */}
        <div style={{...PS.card,marginBottom:20}}>
          {cardHeader('Wage Review','PWD Wage Check',wageStatus.pass?true:wageStatus.status==='Needs Input'?null:false)}
          <div style={grid3}>
            <div><label style={PS.label}>PWD Wage</label><input style={PS.input} placeholder="$0.00" value={pwdWage} onChange={e=>setPwdWage(e.target.value)}/></div>
            <div><label style={PS.label}>From</label><input style={PS.input} placeholder="$0.00" value={wageFrom} onChange={e=>setWageFrom(e.target.value)}/></div>
            <div><label style={PS.label}>To</label><input style={PS.input} placeholder="$0.00" value={wageTo} onChange={e=>setWageTo(e.target.value)}/></div>
          </div>
          <div style={{marginTop:14,padding:'12px 14px',borderRadius:'var(--radius)',background:wageStatus.pass?'var(--green-dim)':'var(--red-dim)',color:wageStatus.pass?'var(--green)':'var(--red)',fontSize:12,fontWeight:500}}>{wageStatus.detail}</div>
        </div>
        </>}

        {/* EPT checker */}
        <EptCard stateVal={stateVal} city={city} telecommute={telecommute} wageFrom={wageFrom} wageTo={wageTo}/>

        {/* Summary */}
        {mode==='diff'&&results&&(
          <div style={{...PS.card}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:14}}>
              <div><div style={{fontSize:10,letterSpacing:'.1em',textTransform:'uppercase',color:'var(--text3)',marginBottom:4}}>Summary</div><div style={{fontSize:14,fontFamily:"'DM Serif Display',serif",color:'var(--text)'}}>Comparison Results</div></div>
              <span style={PS.badge(null)}>{ignoreFmt?'Formatting Ignored':strict?'Strict Mode':'Standard Mode'}</span>
            </div>
            <div style={{display:'grid',gap:10}}>
              {[results.jd,results.mr].map(r=>(
                <div key={r.field} style={{display:'grid',gridTemplateColumns:'minmax(160px,1.1fr) minmax(120px,.7fr) minmax(0,2fr)',gap:12,alignItems:'center',padding:'12px 14px',borderRadius:'var(--radius)',background:'var(--bg3)',fontSize:12}}>
                  <strong style={{color:'var(--text)'}}>{r.field}</strong>
                  <div style={{fontWeight:600,color:r.exact?'var(--green)':'var(--red)'}}>{r.status}</div>
                  <div style={{color:'var(--text2)'}}>{r.detail}</div>
                </div>
              ))}
              <div style={{display:'grid',gridTemplateColumns:'minmax(160px,1.1fr) minmax(120px,.7fr) minmax(0,2fr)',gap:12,alignItems:'center',padding:'12px 14px',borderRadius:'var(--radius)',background:'var(--bg3)',fontSize:12}}>
                <strong style={{color:'var(--text)'}}>Wage Range Validation</strong>
                <div style={{fontWeight:600,color:wageStatus.pass?'var(--green)':'var(--red)'}}>{wageStatus.status}</div>
                <div style={{color:'var(--text2)'}}>{wageStatus.detail}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
    {showExpModal&&(
      <ExperienceVerificationModal
        pwdText={mrRef}
        requirementsText={mrRef}
        letters={expLetters}
        onClose={()=>setShowExpModal(false)}
        onSaveLetter={handleSaveLetter}
        onRemoveLetter={handleRemoveLetter}
      />
    )}
    </>
  );
}

// ── AAO outcome colors ────────────────────────────────────────────────────────

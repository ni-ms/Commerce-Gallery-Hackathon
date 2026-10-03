import React from 'react';
import {AbsoluteFill,Composition,Sequence,Img,Audio,staticFile,useCurrentFrame,interpolate,registerRoot} from 'remotion';
import story from './story.json';
const fps=30;
const Scene=({d,index})=>{
 const f=useCurrentFrame();const entrance=interpolate(f,[0,18],[0,1],{extrapolateRight:'clamp'});
 const green='#234c3b',light='#f5f6f3';
 const base={fontFamily:'Arial, sans-serif',backgroundColor:index===0?green:light,color:index===0?'white':green,padding:'70px 90px'};
 return <AbsoluteFill style={base}>
  <Audio src={staticFile(`voice-${index+1}.wav`)}/>
  <div style={{opacity:entrance,transform:`translateY(${(1-entrance)*18}px)`}}>
   <div style={{fontSize:index===0?110:64,fontWeight:700,marginTop:index===0?210:0}}>{d.title}</div>
   <div style={{fontSize:33,lineHeight:1.4,marginTop:22,maxWidth:1500,color:index===0?'#e8eee4':'#52604f'}}>{d.subtitle}</div>
   {d.kind==='cover'&&<div style={{marginTop:100,fontSize:34,color:'#e8eee4'}}>{d.caption}</div>}
   {d.kind==='cost'&&<div style={{marginTop:130}}><div style={{display:'flex',gap:220}}><div><div style={{fontSize:160,fontWeight:700}}>$6</div><div style={{fontSize:36}}>Eligible buyer route</div></div><div style={{color:'#71806e'}}><div style={{fontSize:160,fontWeight:700}}>$15</div><div style={{fontSize:36}}>Warehouse route</div></div></div><div style={{marginTop:80,fontSize:54,fontWeight:700}}>$9 potential estimated savings</div></div>}
   {d.kind==='text'&&<div style={{marginTop:100}}>{d.lines.map((line,i)=><div key={line} style={{display:'flex',gap:45,marginBottom:66,alignItems:'baseline'}}><span style={{fontSize:38,color:'#7f906e'}}>{String(i+1).padStart(2,'0')}</span><span style={{fontSize:43,maxWidth:1450,lineHeight:1.3}}>{line}</span></div>)}</div>}
   {d.image&&<div style={{display:'flex',gap:70,marginTop:55,alignItems:'center'}}><div style={{width:660,fontSize:44,lineHeight:1.6}}>{d.kind==='inspection'?<>Opened condition<br/>Buyer route blocked<br/>Reservation released<br/>Fresh approval required</>:d.image==='live-review.jpg'?<>Three role sessions<br/>Two Moss queries<br/>Saved handoff receipts<br/>Awaiting approval</>:<>Condition confirmation<br/>Optional photos<br/>Fresh review when facts change</>}</div><div style={{width:930,height:610,overflow:'hidden',background:'#ffffff'}}><Img src={staticFile(d.image)} style={d.kind==='inspection'?{width:930,transform:'translateY(-550px)'}:d.image==='live-review.jpg'?{width:930,transform:'translateY(-240px)'}:{width:930,height:610,objectFit:'contain'}}/></div></div>}
  </div>
  {index!==0&&d.caption&&<div style={{position:'absolute',bottom:75,left:90,right:90,fontSize:25,color:'#52604f'}}>{d.caption}</div>}
  <div style={{position:'absolute',bottom:0,left:0,height:6,width:`${100*f/(d.duration*fps)}%`,background:index===0?'#b0c49a':'#234c3b'}}/>
 </AbsoluteFill>;
};
const Video=()=>{let from=0;return <AbsoluteFill>{story.map((d,index)=>{const start=from;from+=d.duration*fps;return <Sequence key={index} from={start} durationInFrames={d.duration*fps}><Scene d={d} index={index}/></Sequence>;})}</AbsoluteFill>;};
registerRoot(()=> <Composition id="SmarterReturns" component={Video} durationInFrames={5400} fps={fps} width={1920} height={1080}/>);

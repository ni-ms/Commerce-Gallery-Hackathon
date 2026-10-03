import React from 'react';
import {AbsoluteFill,Composition,Sequence,Img,Audio,staticFile,useCurrentFrame,interpolate,Easing,registerRoot} from 'remotion';
import story from './walkthrough-story.json';
const fps=30;
const Cursor=({target,frames})=>{
 const f=useCurrentFrame(); const progress=interpolate(f,[Math.max(0,frames-65),frames-18],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.inOut(Easing.cubic)});
 const x=interpolate(progress,[0,1],[target[0]-90,target[0]])*1.5,y=interpolate(progress,[0,1],[target[1]-65,target[1]])*1.5;
 const ripple=interpolate(f,[frames-18,frames-1],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 return <><div style={{position:'absolute',left:x-36,top:y-36,width:72,height:72,border:'4px solid #c89736',borderRadius:'50%',opacity:ripple>0?1-ripple:0,transform:`scale(${1+ripple})`}}/><svg width="38" height="46" viewBox="0 0 28 34" style={{position:'absolute',left:x,top:y,filter:'drop-shadow(0 2px 3px #0005)'}}><path d="M2 2 L2 26 L9 20 L15 32 L21 29 L15 17 L25 16 Z" fill="white" stroke="#234c3b" strokeWidth="2"/></svg></>;
};
const Shot=({shot})=>{
 return <AbsoluteFill><Img src={staticFile(`walkthrough/${shot[0]}.png`)} style={{width:1920,height:1080,objectFit:'contain'}}/>{shot[2]&&<Cursor target={shot[2]} frames={Math.round(shot[1]*fps)}/>}</AbsoluteFill>;
};
const Chapter=({d,index})=>{let at=0;return <AbsoluteFill style={{background:'#f5f6f3'}}><Audio src={staticFile(`walkthrough/narration-${index+1}.mp3`)}/>{d.shots.map((shot,i)=>{let from=at;at+=shot[1]*fps;return <Sequence key={i} from={from} durationInFrames={shot[1]*fps}><Shot shot={shot}/></Sequence>;})}<div style={{position:'absolute',bottom:0,left:0,right:0,height:76,background:'rgba(27,56,43,0.96)',display:'flex',alignItems:'center',justifyContent:'space-between',padding:'0 48px',fontFamily:'Arial, sans-serif',color:'white'}}><span style={{fontSize:31,fontWeight:600}}>{d.title}</span><span style={{fontSize:22,color:'#d9e4d3'}}>{index===6||index===7?'Saved live review':'Interactive demo scenarios'}</span></div></AbsoluteFill>;};
const Video=()=>{let at=0;return <AbsoluteFill>{story.map((d,i)=>{let from=at;at+=d.duration*fps;return <Sequence key={i} from={from} durationInFrames={d.duration*fps}><Chapter d={d} index={i}/></Sequence>;})}</AbsoluteFill>;};
registerRoot(()=> <Composition id="SmarterReturnsWalkthrough" component={Video} durationInFrames={5400} fps={fps} width={1920} height={1080}/>);

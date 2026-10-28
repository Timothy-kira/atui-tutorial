/* Reproducible presentation timelines; every action stays inside the mock UI. */
(() => {
  const api = window.MaisonShowcase;
  const $ = selector => document.querySelector(selector);
  let current = null, lastKey = null;
  function ensure(context) {
    if (current !== context || context.controller.signal.aborted) throw new DOMException('Stopped', 'AbortError');
  }
  function pause(milliseconds, context) {
    ensure(context);
    return new Promise((resolve, reject) => {
      const signal = context.controller.signal;
      const abort = () => {clearTimeout(timer); reject(new DOMException('Stopped', 'AbortError'));};
      const timer = setTimeout(() => {signal.removeEventListener('abort', abort); resolve();}, milliseconds);
      signal.addEventListener('abort', abort, {once:true});
    });
  }
  async function until(predicate, context, timeout = 18000) {
    const deadline = performance.now() + timeout;
    while (performance.now() < deadline) {
      ensure(context);
      const result = predicate(); if (result) return result;
      await pause(50, context);
    }
    throw new Error('Presentation element was not ready');
  }
  async function element(selector, context) {
    return until(() => {const node = $(selector); return node && node.getBoundingClientRect().width && !node.disabled ? node : null;}, context);
  }
  async function animation(node, frames, options, context) {
    ensure(context);
    const motion = node.animate(frames, {...options, duration:matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : options.duration, fill:'forwards'});
    context.animations.add(motion);
    await motion.finished;
    ensure(context);
    return motion;
  }
  function cursor(context) {
    if (context.cursor) return context.cursor;
    const node = document.createElement('div'); node.className = 'demo-flow-cursor'; node.setAttribute('aria-hidden','true');
    node.innerHTML = '<img src="../assets/logos/teaching-cursor.svg" alt="">';
    node.style.transform = `translate(${innerWidth * .67}px,${innerHeight * .7}px)`;
    document.body.append(node); context.cursor = node;
    context.point = {x:innerWidth * .67,y:innerHeight * .7};
    return node;
  }
  async function move(selector, context) {
    const node = await element(selector, context);
    const scroller = node.closest('.workspace-body,.messages');
    if (scroller) {
      const box = node.getBoundingClientRect(), clip = scroller.getBoundingClientRect();
      if (box.bottom > clip.bottom - 12 || box.top < clip.top + 12) {
        scroller.scrollTo({top:scroller.scrollTop + box.top - clip.top - scroller.clientHeight * .45,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
        await pause(400,context);
      }
    }
    const pointer = cursor(context), box = node.getBoundingClientRect();
    const end = {x:box.left + box.width * .5 - 5,y:box.top + box.height * .5 - 4};
    const begin = context.point;
    const motion = await animation(pointer,[{transform:`translate(${begin.x}px,${begin.y}px)`,opacity:1},{transform:`translate(${end.x}px,${end.y}px)`,opacity:1}],{duration:600,easing:'cubic-bezier(.4,0,.2,1)'},context);
    pointer.style.transform = `translate(${end.x}px,${end.y}px)`; context.point = end;
    motion.cancel(); context.animations.delete(motion);
    return node;
  }
  async function click(selector, context) {
    const node = await move(selector, context), point = context.point;
    const motion = await animation(context.cursor,[{transform:`translate(${point.x}px,${point.y}px) scale(1)`},{transform:`translate(${point.x}px,${point.y}px) scale(.85)`},{transform:`translate(${point.x}px,${point.y}px) scale(1)`}],{duration:180,easing:'ease-in-out'},context);
    motion.cancel(); context.animations.delete(motion);
    node.click();
    await pause(240, context);
  }
  async function type(selector, value, context, speed = 24) {
    const input = await move(selector,context);
    input.classList.add('demo-typing'); input.value = '';
    for (const character of value) {
      ensure(context); input.value += character; input.dispatchEvent(new Event('input',{bubbles:true}));
      await pause(speed,context);
    }
    input.dispatchEvent(new Event('change',{bubbles:true})); input.classList.remove('demo-typing');
    await pause(220,context);
  }
  async function ask(text, context) {
    await type('.composer textarea',text,context,18);
    await click('.composer .send',context);
  }
  async function highlight(selector, context, milliseconds = 1200) {
    const node = await element(selector,context);
    node.classList.add('demo-action-highlight');
    await pause(milliseconds,context); node.classList.remove('demo-action-highlight');
  }
  async function cue(seconds,context) {
    // Use the narrated media clock, not the cumulative length of previous actions.
    while(api.narrationTime<seconds){ensure(context);await pause(25,context);}
  }
  async function recommend(context) {
    await cue(2,context);
    await click('#agent-tab',context);
    await cue(6.5,context);
    await click('[data-prompt="Build a meal under S$60"]',context);
    await element('#recommendation-filters',context);
    await cue(9.3,context);
    await type('#recommendation-filters [name="diners"]','2',context,120);
    await cue(11.2,context);
    await type('#recommendation-filters [name="budget"]','60',context,120);
    await cue(13,context);
    await move('#recommendation-filters [name="diet"]',context);
    await cue(14.4,context);
    await type('#recommendation-filters [name="calories"]','650',context,120);
    await until(() => !api.busy,context);
    await cue(16.9,context);
    await click('#recommendation-filters .primary',context);
    await element('[data-add-portions="chicken"]',context);
    await highlight('.workspace .dish-row',context);
    await cue(22.4,context);
    await click('[data-add-portions="chicken"]',context);
    await cue(23.7,context);
    await click('[data-add-portions="chicken"]',context);
    await cue(25.5,context);
  }
  async function explain(context) {
    await cue(2.2,context);
    await type('.composer textarea','What’s in the Herb-Roasted Chicken? How many calories does it have, and does it contain allergens?',context,18);
    await cue(9.4,context);
    await click('.composer .send',context);
    await element('.workspace .fact-grid',context);
    await highlight('.workspace .surface-copy',context,1100);
    await highlight('.workspace .fact:first-child',context,1000);
    await highlight('.workspace .fact:nth-child(2)',context,1000);
    await cue(15.9,context);
    await click('.workspace-close',context);
    await cue(18.1,context);
    await click('.surface-reference',context);
    await element('.workspace .fact-grid',context);
    await cue(20.1,context);
  }
  async function order(context) {
    await cue(.1,context);
    await ask('Review my pickup order.',context);
    await element('[data-quantity="lemonade"][data-step="-1"]',context);
    await cue(2.7,context);
    await click('[data-quantity="lemonade"][data-step="-1"]',context);
    await element('.workspace .total',context);
    await highlight('.workspace .total',context,1400);
    await cue(8,context);
    await click('[data-confirm-order]',context);
    await element('.workspace .confirmation',context);
    await until(() => $('.order-status-card')?.dataset.stage === 'ready',context,12000);
    await cue(16.1,context);
  }
  function stop() {
    const previous = current; current = null; lastKey = null;
    if (previous) {previous.controller.abort(); previous.animations.forEach(motion => motion.cancel()); previous.cursor?.remove();}
    document.documentElement.classList.remove('demo-scripted');
    document.querySelectorAll('.demo-action-highlight,.demo-typing').forEach(node => node.classList.remove('demo-action-highlight','demo-typing'));
    $('.demo-flow-error')?.remove(); api.stopWork();
  }
  async function play(name, runId) {
    const routines = {recommend,explain,order}; if (!routines[name]) return;
    const key = `${runId}:${name}`; if (key === lastKey) return;
    stop(); lastKey = key;
    const context = {controller:new AbortController(),animations:new Set(),cursor:null,point:null}; current = context;
    document.documentElement.classList.add('demo-scripted');
    try {
      api.prepareFlow(name);
      api.startNarrationClock(name,.43);
      api.notify('flow-started',{flow:name});
      await routines[name](context);
      if (context.cursor) await animation(context.cursor,[{opacity:1},{opacity:0}],{duration:300},context);
      ensure(context);
      context.animations.forEach(motion => motion.cancel()); context.cursor?.remove();
      document.documentElement.classList.remove('demo-scripted');
      api.notify('flow-complete',{flow:name});
    } catch (error) {
      if (error.name === 'AbortError' || current !== context) return;
      api.stopWork();
      context.animations.forEach(motion => motion.cancel()); context.cursor?.remove();
      document.documentElement.classList.remove('demo-scripted');
      const retry = document.createElement('button'); retry.className = 'demo-flow-error'; retry.textContent = 'Replay this demonstration';
      retry.addEventListener('click',() => {lastKey = null; play(name,runId);}); document.body.append(retry);
      api.notify('flow-error',{flow:name});
    }
  }
  window.MaisonShowcaseFlows = {play,stop};
  let fragmentState=null;
  function enterChapter(){
    const state=new URLSearchParams(location.hash.slice(1));
    const chapter=state.get('chapter'),runId=Number(state.get('run'))||0;
    const key=`${runId}:${chapter}`;
    if(!chapter||key===fragmentState)return;
    fragmentState=key;api.setRunId(runId);
    if(['recommend','explain','order'].includes(chapter)){play(chapter,runId);return;}
    stop();
    if(chapter==='explore')api.startExplore();
    if(chapter==='prepare')api.reset();
  }
  addEventListener('hashchange',enterChapter);
  enterChapter();
  api.notify('ready',{flowsReady:true});
})();

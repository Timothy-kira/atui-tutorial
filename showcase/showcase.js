/* Standalone, deterministic presentation UI. No service, model or SDK calls. */
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const menu = window.MAISON_SHOWCASE_MENU;
  const categories = [['all', 'All'], ['appetizer', 'Starters'], ['main', 'Mains'], ['pasta_pizza', 'Pasta & pizza'], ['dessert', 'Desserts'], ['drink', 'Drinks']];
  const escape = value => String(value).replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  const money = value => 'S$' + value.toFixed(2);
  const photo = dish => `<img src="${escape(dish.image)}" alt="${escape(dish.name)}" loading="eager">`;
  const cart = new Map();
  let view = 'menu', category = 'all', busy = false, generation = 0, textFrame = null, scrollFrame = null;
  let workspace = null, closeTimer = null, runId = 0, preparing = Promise.resolve();
  let orderStage = 'preparing', manualScrollAt = -Infinity;
  let exploreAudioMode=false, exploreFinished=false;
  let narrationClock=null;
  const narrationDurations={explore:14.213,recommend:25.809,explain:20.352,order:16.274};
  function startNarrationClock(flow,lead=0) {
    narrationClock={flow,run:runId,time:0,anchor:performance.now()+lead*1000,duration:narrationDurations[flow],paused:false,ended:false};
  }
  function narrationTime() {
    if(!narrationClock)return 0;
    if(narrationClock.ended)return narrationClock.duration;
    return Math.min(narrationClock.duration,narrationClock.time+(narrationClock.paused?0:Math.max(0,performance.now()-narrationClock.anchor)/1000));
  }
  function syncNarrationClock(data) {
    if(!narrationClock||data.flow!==narrationClock.flow||data.runId!==narrationClock.run||!Number.isFinite(data.time))return;
    narrationClock.time=Math.max(0,data.time);narrationClock.anchor=performance.now();
    narrationClock.duration=Number(data.duration)||narrationClock.duration;
    narrationClock.paused=Boolean(data.paused);narrationClock.ended=Boolean(data.ended);
  }
  const timers = new Set();
  const preferences = {diners:2, diet:'any', budget:'', calories:'', allergens:[]};
  const later = (callback, milliseconds) => {
    const token = generation;
    const timer = setTimeout(() => {timers.delete(timer); if (token === generation) callback();}, milliseconds);
    timers.add(timer);
  };
  function stopScroll() {cancelAnimationFrame(scrollFrame); scrollFrame = null; document.documentElement.classList.remove('demo-pointer');}
  function stopWork() {generation++; timers.forEach(clearTimeout); timers.clear(); cancelAnimationFrame(textFrame); busy = false;}
  function updateCount() {$('#cart-count').textContent = [...cart.values()].reduce((sum, count) => sum + count, 0);}
  function addDish(id) {cart.set(id, (cart.get(id) || 0) + 1); updateCount();}
  function renderMenu() {
    $('.menu-categories').innerHTML = categories.map(([id, label]) => `<button data-category="${id}" aria-pressed="${category === id}">${label}</button>`).join('');
    $('.menu-list').innerHTML = categories.filter(([id]) => id !== 'all' && (category === 'all' || category === id)).map(([id, label]) => `<section class="menu-category"><h2>${label}</h2>${menu.filter(dish => dish.category === id).map(dish => `<article class="menu-item"><button class="menu-photo" data-detail="${dish.id}" aria-label="View ${escape(dish.name)}">${photo(dish)}</button><div class="menu-item-copy"><div class="menu-item-heading"><h3>${escape(dish.name)}</h3><strong>${money(dish.price)}</strong></div><p class="menu-description">${escape(dish.description)}</p>${dish.vegan || dish.vegetarian ? `<p class="diet">${dish.vegan ? 'Plant-based' : 'Vegetarian'}</p>` : ''}${!dish.available ? '<p class="menu-description">Unavailable today</p>' : ''}</div><button class="menu-add" data-add="${dish.id}" aria-label="Add ${escape(dish.name)}" ${dish.available ? '' : 'disabled'}>+</button></article>`).join('')}</section>`).join('');
  }
  function selectView(next) {
    view = next;
    $('#menu-view').hidden = next !== 'menu'; $('#agent-view').hidden = next !== 'agent';
    $('#menu-tab').setAttribute('aria-selected', String(next === 'menu'));
    $('#agent-tab').setAttribute('aria-selected', String(next === 'agent'));
    $('.view-tab-indicator').style.transform = next === 'agent' ? 'translateX(100%)' : 'translateX(0)';
    window.scrollTo(0, 0);
  }
  function message(role, text = '') {
    $('.conversation').classList.add('has-messages');
    const element = document.createElement('div'); element.className = 'message ' + role; element.textContent = text;
    $('.messages').append(element); return element;
  }
  function revealReplyStart(element) {
    if (!element.isConnected || performance.now() - manualScrollAt < 1000) return;
    const scroller = $('.messages'), clip = scroller.getBoundingClientRect(), box = element.getBoundingClientRect();
    const firstLines = Math.min(box.height,parseFloat(getComputedStyle(element).lineHeight) * 2);
    if (box.top < clip.top + 12 || box.top + firstLines > clip.bottom - 12) {
      scroller.scrollTo({top:Math.max(0,scroller.scrollTop + box.top - clip.top - 20),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    }
  }
  $('.messages').addEventListener('wheel',() => {manualScrollAt = performance.now();},{passive:true});
  $('.messages').addEventListener('touchstart',() => {manualScrollAt = performance.now();},{passive:true});
  function stream(text, done) {
    const element = message('assistant'); const token = generation;
    let revealed = false;
    later(() => revealReplyStart(element),650);
    let began = null;
    function frame(time) {
      if (token !== generation) return;
      if (began === null) began = time;
      const length = Math.min(text.length, Math.floor((time - began) / 12) + 1);
      element.textContent = text.slice(0, length);
      if (!revealed && time - began >= 120) {revealed = true; revealReplyStart(element);}
      if (length < text.length) textFrame = requestAnimationFrame(frame);
      else {busy = false; done?.();}
    }
    textFrame = requestAnimationFrame(frame);
  }
  function miniCard(title) {
    $('.conversation').classList.add('has-messages');
    const existing = $('.surface-reference');
    if (existing?.dataset.surfaceTitle === title) return;
    $('.surface-reference')?.remove();
    const button = document.createElement('button'); button.className = 'mini-card surface-reference';
    button.dataset.surfaceTitle = title;
    button.innerHTML = `<span>${escape(title)}</span><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="16"/><path d="M11 18h14m-6-6 6 6-6 6"/></svg>`;
    button.addEventListener('click', () => {if (workspace) openPanel(workspace.title, workspace.render);});
    $('.messages').append(button);
  }
  function openPanel(title, render) {
    clearTimeout(closeTimer);
    const html = render(), previous = workspace, body = $('.workspace-body');
    workspace = {title, render, html};
    const panel = $('.workspace'); panel.classList.remove('is-closing'); panel.hidden = false;
    $('.agent-layout').classList.add('has-workspace'); $('#workspace-title').textContent = title;
    if (previous?.title === title && body.querySelector('.surface-content')) {
      if (previous.html !== html) {
        const scrollTop = body.scrollTop;
        body.querySelector('.surface-content').innerHTML = html;
        body.scrollTop = scrollTop;
      }
      miniCard(title);return;
    }
    body.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    const token = workspace;
    later(() => {
      if (workspace !== token || panel.hidden) return;
      body.innerHTML = `<div class="surface-content">${html}</div>`;
      body.scrollTop = 0;
    }, 380);
    miniCard(title);
  }
  function closePanel() {
    $('.workspace').classList.add('is-closing');
    closeTimer = setTimeout(() => {$('.workspace').hidden = true; $('.workspace').classList.remove('is-closing'); $('.agent-layout').classList.remove('has-workspace');}, 280);
  }
  function filterForm() {
    return `<p class="surface-copy">Set your preferences and choose from matching dishes.</p><form id="recommendation-filters"><div class="filter-grid"><label>People<input name="diners" type="number" min="1" max="12" value="${preferences.diners}"></label><label>Diet<select name="diet">${[['any','Any diet'],['vegetarian','Vegetarian'],['vegan','Vegan']].map(([id,label]) => `<option value="${id}" ${preferences.diet === id ? 'selected' : ''}>${label}</option>`).join('')}</select></label><label>Max kcal / person / dish<input name="calories" type="number" min="0" placeholder="No limit" value="${preferences.calories}"></label><label>Max total / dish (S$)<input name="budget" type="number" min="0" placeholder="No limit" value="${preferences.budget}"></label></div><p class="surface-copy">Exclude declared allergens</p><div class="allergens">${['egg','fish','gluten','milk','nuts','sesame','shellfish'].map(name => `<label><input name="allergens" type="checkbox" value="${name}" ${preferences.allergens.includes(name) ? 'checked' : ''}>${name[0].toUpperCase() + name.slice(1)}</label>`).join('')}</div><button class="primary">Update recommendations</button></form>`;
  }
  function matches() {
    const ranked = ['chicken', 'risotto', 'cauliflower', 'salmon', 'pesto'];
    return menu.filter(dish => dish.available && ['main', 'pasta_pizza'].includes(dish.category))
      .filter(dish => preferences.diet === 'any' || dish[preferences.diet])
      .filter(dish => !preferences.budget || dish.price * preferences.diners <= Number(preferences.budget))
      .filter(dish => !preferences.calories || dish.calories_kcal <= Number(preferences.calories))
      .filter(dish => !dish.allergens.some(allergen => preferences.allergens.includes(allergen)))
      .sort((a,b) => (ranked.includes(a.id) ? ranked.indexOf(a.id) : 99) - (ranked.includes(b.id) ? ranked.indexOf(b.id) : 99)).slice(0,3);
  }
  function recommendationRows(dishes) {
    return `<button class="quiet edit-preferences" data-edit-filters><svg viewBox="0 0 20 24" aria-hidden="true"><path d="m13 5-7 7 7 7"/></svg><span>Edit preferences</span></button><p class="surface-copy">${dishes.length} options for ${preferences.diners} people. Choose dishes for your pickup order.</p>${dishes.length ? dishes.map(dish => `<article class="dish-row">${photo(dish)}<div class="dish-row-main"><h3>${escape(dish.name)}</h3><p>${money(dish.price)} / portion</p></div><div class="quantity recommendation-quantity" role="group" aria-label="${escape(dish.name)} quantity"><button data-recommend-quantity="${dish.id}" data-step="-1" aria-label="Remove one ${escape(dish.name)}" ${cart.has(dish.id) ? '' : 'disabled'}>−</button><output aria-live="polite">${cart.get(dish.id) || 0}</output><button data-add-portions="${dish.id}" data-recommend-quantity="${dish.id}" data-step="1" aria-label="Add one ${escape(dish.name)}">+</button></div></article>`).join('') : '<p class="empty">No matches for these preferences. Try adjusting your limits.</p>'}`;
  }
  function showRecommendations() {
    const dishes = matches();
    openPanel('Recommended for pickup', () => recommendationRows(dishes));
    busy = true;
    const facts = dishes.map(dish => `${dish.name}: ${preferences.diners} portions, ${money(dish.price * preferences.diners)} total, ${dish.calories_kcal} kcal per person. Declared allergens: ${dish.allergens.join(', ') || 'none listed'}.`).join('\n\n');
    stream(dishes.length ? `Here are my recommendations based on your preferences. Each is an alternative for your pickup order.\n\n${facts}` : 'No dishes match all of those preferences. Please adjust the filters to see more options.');
  }
  function explanation(dish) {
    const images = dish.id === 'lemonade'
      ? `<div class="lemonade-gallery" aria-label="Three views of our lemonade">${['01','02','03'].map((number,index)=>`<img src="images/lemonade-${number}.png" alt="Lemonade — ${['front view','overhead view','close detail'][index]}" loading="eager">`).join('')}</div>`
      : photo(dish).replace('<img ', '<img class="explain-photo" ');
    return `${images}<p class="surface-copy">${escape(dish.preparation)}</p><div class="fact-grid"><div class="fact"><span>Energy / serving</span><strong>${dish.calories_kcal} kcal</strong></div><div class="fact"><span>Declared allergens</span><strong>${escape(dish.allergens.join(', ') || 'None listed')}</strong></div></div><button class="primary" data-add="${dish.id}">Add to order · ${money(dish.price)}</button>`;
  }
  function cartContents() {
    const dishes = menu.filter(dish => cart.has(dish.id));
    if (!dishes.length) return '<p class="empty">Your pickup order is empty. Explore the menu or ask for recommendations to add a dish.</p>';
    const total = dishes.reduce((sum,dish) => sum + dish.price * cart.get(dish.id), 0);
    const calories = dishes.reduce((sum,dish) => sum + dish.calories_kcal * cart.get(dish.id), 0);
    return `${dishes.map(dish => `<article class="dish-row">${photo(dish)}<div class="dish-row-main"><h3>${escape(dish.name)}</h3><p>${money(dish.price * cart.get(dish.id))}</p></div><div class="quantity"><button data-quantity="${dish.id}" data-step="-1" aria-label="Remove one ${escape(dish.name)}">−</button><span>${cart.get(dish.id)}</span><button data-quantity="${dish.id}" data-step="1" aria-label="Add one ${escape(dish.name)}">+</button></div></article>`).join('')}<div class="total"><span>Total</span><strong>${money(total)}</strong></div><p class="surface-copy">${calories.toLocaleString()} kcal total · illustrative estimates</p><button class="primary" data-confirm-order>Confirm pickup order</button>`;
  }
  function orderStatus() {
    const ready = orderStage === 'ready';
    return `<section class="confirmation order-status-card" data-stage="${orderStage}" aria-live="polite"><ol class="order-stages" aria-label="Pickup order progress"><li class="is-complete"><span>1</span><b>Confirmed</b></li><li class="${ready ? 'is-complete' : 'is-active'}"><span>2</span><b>Preparing</b></li><li class="${ready ? 'is-active is-ready' : ''}"><span>3</span><b>Ready for pickup</b></li></ol><div class="order-pickup-code"><span>${ready ? 'Collect at the pickup counter' : 'Pickup number'}</span><strong>M024</strong></div></section>`;
  }
  function updateOrderStage(stage) {
    orderStage = stage;
    if (workspace?.title !== 'Pickup order status') return;
    const card = $('.order-status-card');if (!card) return;
    card.dataset.stage = stage;
    const steps = card.querySelectorAll('.order-stages li');
    steps[1].className = 'is-complete';
    steps[2].className = 'is-active is-ready';
    card.querySelector('.order-pickup-code>span').textContent = 'Collect at the pickup counter';
    workspace.html = orderStatus();
  }
  function confirmOrder() {
    orderStage = 'preparing';openPanel('Pickup order status',orderStatus);
    cart.clear();updateCount();
    if (!busy) {busy = true;stream('Your pickup order is confirmed. The kitchen is preparing your meal. Your pickup number is M024. Please collect it at the pickup counter when it is ready.');}
    if(narrationClock?.flow==='order'&&new URLSearchParams(location.hash.slice(1)).get('timing')==='audio') {
      const finish=()=>{if(narrationTime()>=14.5)updateOrderStage('ready');else later(finish,50);};
      finish();
    } else later(()=>updateOrderStage('ready'),6500);
  }
  function sendPrompt(prompt) {
    if (busy || !prompt.trim()) return;
    stopWork(); busy = true; selectView('agent'); message('user', prompt.trim());
    const lower = prompt.toLowerCase();
    if (/order|checkout|cart|total/.test(lower)) {
      stream('Please review the dishes, quantities and total in your order, then select Confirm pickup order when you are ready. Your meal will be prepared for collection at the pickup counter.');
      openPanel('Review your pickup order', cartContents);
    } else if (/lemonade|ingredient|calorie|allergen|what.*in|explain/.test(lower)) {
      const dish = menu.find(dish => lower.includes(dish.name.toLowerCase()) || lower.includes(dish.id)) || menu.find(dish => dish.id === 'lemonade');
      stream(`${dish.name}: ${dish.description} ${dish.preparation}\n\nIt has approximately ${dish.calories_kcal} kcal per serving. Declared allergens: ${dish.allergens.join(', ') || 'none listed'}. You can review the details in the panel.`);
      openPanel(dish.name, () => explanation(dish));
    } else {
      preferences.diners = /four|4 people/.test(lower) ? 4 : 2;
      preferences.diet = /vegan/.test(lower) ? 'vegan' : /vegetarian/.test(lower) ? 'vegetarian' : 'any';
      preferences.budget = /60/.test(lower) ? '60' : ''; preferences.calories = ''; preferences.allergens = [];
      stream('Please set your group size, budget and dietary preferences in the panel. Select Update recommendations, and I’ll suggest a few matching dishes.');
      openPanel('Find dishes for pickup', filterForm);
    }
  }
  $('#menu-tab').addEventListener('click', () => {stopScroll(); selectView('menu');});
  $('#agent-tab').addEventListener('click', () => {stopScroll(); selectView('agent');});
  $('.table-toggle').addEventListener('click', () => {selectView('agent'); openPanel('Review your pickup order', cartContents);});
  $('.workspace-close').addEventListener('click', closePanel);
  $('.composer').addEventListener('submit', event => {event.preventDefault(); const input = $('.composer textarea'); const value = input.value; if (!busy && value.trim()) {input.value = ''; sendPrompt(value);}});
  $('.composer textarea').addEventListener('keydown', event => {if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); $('.composer').requestSubmit();}});
  document.addEventListener('submit', event => {
    if (event.target.id !== 'recommendation-filters') return;
    event.preventDefault(); if (busy) return;
    const data = new FormData(event.target);
    preferences.diners = Math.max(1, Math.min(12, Number(data.get('diners')) || 2));
    preferences.diet = data.get('diet'); preferences.budget = data.get('budget'); preferences.calories = data.get('calories'); preferences.allergens = data.getAll('allergens');
    showRecommendations();
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    if (button.dataset.category) {category = button.dataset.category; renderMenu(); window.scrollTo(0,0);}
    if (button.dataset.add) addDish(button.dataset.add);
    if (button.dataset.recommendQuantity) {
      const id = button.dataset.recommendQuantity;
      const quantity = Math.max(0,(cart.get(id) || 0) + Number(button.dataset.step));
      if (quantity) cart.set(id,quantity); else cart.delete(id);
      updateCount();
      const control = button.closest('.recommendation-quantity');
      control.querySelector('output').textContent = quantity;
      control.querySelector('[data-step="-1"]').disabled = quantity === 0;
    }
    if (button.dataset.prompt) sendPrompt(button.dataset.prompt);
    if (button.hasAttribute('data-edit-filters')) openPanel('Find dishes for pickup', filterForm);
    if (button.dataset.quantity) {const id = button.dataset.quantity; const quantity = Math.max(0,(cart.get(id) || 0) + Number(button.dataset.step)); if (quantity) cart.set(id,quantity); else cart.delete(id); updateCount(); openPanel('Review your pickup order', cartContents);}
    if (button.hasAttribute('data-confirm-order') && cart.size) {
      confirmOrder();
    }
    if (button.dataset.detail) {
      const dish = menu.find(dish => dish.id === button.dataset.detail);
      $('.dish-detail').innerHTML = `${photo(dish)}<div class="detail-body"><h2>${escape(dish.name)}</h2><p>${escape(dish.description)}</p><p>${escape(dish.preparation)}</p><button class="primary" data-add="${dish.id}" ${dish.available ? '' : 'disabled'}>Add to order · ${money(dish.price)}</button></div>`;
      $('.dish-dialog').showModal();
    }
    if (button.classList.contains('dialog-close')) $('.dish-dialog').close();
  });
  document.addEventListener('error', event => {if (event.target instanceof HTMLImageElement && !event.target.src.endsWith('placeholder.svg')) event.target.src = 'images/placeholder.svg';}, true);

  // File URLs have an opaque origin; validate the parent window and channel.
  const channel = 'devfest-maison-presentation';
  const embedded = window.parent !== window;
  let parentOrigin = '*';
  if (document.referrer) {const origin = new URL(document.referrer).origin; if (origin !== 'null') parentOrigin = origin;}
  const notify = (type, detail = {}) => {if (embedded) window.parent.postMessage({channel, type, runId, ...detail}, parentOrigin);};
  const nextPaint = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const receivedCommands = new Set();
  function reset() {
    narrationClock=null;
    exploreAudioMode=false;exploreFinished=false;
    stopScroll(); stopWork(); clearTimeout(closeTimer); category = 'all'; cart.clear(); updateCount(); renderMenu();
    $('.messages').replaceChildren(); $('.conversation').classList.remove('has-messages'); $('.workspace').hidden = true; $('.workspace').classList.remove('is-closing'); $('.agent-layout').classList.remove('has-workspace'); workspace = null;
    $('.composer textarea').value = ''; $('.dish-dialog').close(); selectView('menu');
  }
  function prepareFlow(name) {
    if (name==='recommend' && view==='menu') {stopScroll();stopWork();return;}
    const continuing = view === 'agent' && ((name === 'explain' && workspace?.title === 'Recommended for pickup') || (name === 'order' && workspace?.title === menu.find(dish=>dish.id==='chicken').name));
    if (continuing) {
      stopWork();
      if (name === 'order') {cart.set('lemonade',1);updateCount();}
      return;
    }
    reset();
    preferences.diners = 2; preferences.diet = 'any'; preferences.budget = '60'; preferences.calories = '650'; preferences.allergens = [];
    if (name === 'recommend') return;
    selectView('agent');
    cart.set('chicken',2); updateCount();
    message('user','Build a meal under S$60 for two people.');
    message('assistant','Here are three options that fit your budget. Two portions of the Herb-Roasted Chicken cost S$56 in total.');
    if (name === 'explain') openPanel('Recommended for pickup', () => recommendationRows(matches()));
    if (name === 'order') {
      cart.set('lemonade',1); updateCount();
      const dish = menu.find(item => item.id === 'chicken');
      message('user','What’s in the Herb-Roasted Chicken?');
      message('assistant',`${dish.preparation}\n\nApproximately ${dish.calories_kcal} kcal per serving. Declared allergens: ${dish.allergens.join(', ') || 'none listed'}.`);
      message('user','I’ve also selected a lemonade. Let’s review the pickup order before confirming.');
      openPanel(dish.name, () => explanation(dish));
    }
  }
  function scrollMenu(speed) {
    stopScroll(); const token = generation; let previous = null; let position = window.scrollY;
    function frame(time) {
      if (generation !== token || view !== 'menu') return;
      if (previous !== null) position += speed * Math.min(time - previous,100) / 1000;
      previous = time;
      const bottom = Math.max(0,document.documentElement.scrollHeight - innerHeight);
      window.scrollTo(0,Math.min(position,bottom));
      if (position >= bottom - 1) {scrollFrame = null; notify('explore-complete'); return;}
      scrollFrame = requestAnimationFrame(frame);
    }
    scrollFrame = requestAnimationFrame(frame);
  }
  function syncExploreProgress(value) {
    if (!exploreAudioMode || view!=='menu' || !Number.isFinite(value)) return;
    const progress=Math.max(0,Math.min(1,value));
    const bottom=Math.max(0,document.documentElement.scrollHeight-innerHeight);
    window.scrollTo(0,bottom*progress);
    if (progress>=1 && !exploreFinished) {
      exploreFinished=true;const token=generation;
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        if (token!==generation || view!=='menu' || !exploreAudioMode) return;
        window.scrollTo(0,Math.max(0,document.documentElement.scrollHeight-innerHeight));
        notify('explore-complete');
      }));
    }
  }
  function scrollExploreNarration() {
    stopScroll();const token=generation;
    function frame() {
      if(token!==generation||view!=='menu'||!exploreAudioMode||!narrationClock)return;
      syncExploreProgress(narrationTime()/narrationClock.duration);
      if(!exploreFinished)scrollFrame=requestAnimationFrame(frame);else scrollFrame=null;
    }
    scrollFrame=requestAnimationFrame(frame);
  }
  window.addEventListener('message', async event => {
    if (event.source !== window.parent || event.data?.channel !== channel || (parentOrigin !== '*' && event.origin !== parentOrigin) || typeof event.data.runId !== 'number') return;
    const data = event.data;
    if (data.runId < runId) return;
    runId = data.runId;
    if (data.commandId !== undefined) {
      notify('ack',{commandId:data.commandId});
      if (receivedCommands.has(data.commandId)) return;
      receivedCommands.add(data.commandId);
      if (receivedCommands.size > 200) receivedCommands.delete(receivedCommands.values().next().value);
    }
    if (data.action === 'hello') {notify('ready',{flowsReady:Boolean(window.MaisonShowcaseFlows)});return;}
    if (data.action === 'narration-clock') {syncNarrationClock(data);return;}
    if (data.action === 'stop') {stopScroll(); window.MaisonShowcaseFlows?.stop(); return;}
    if (data.action === 'pointer') {document.documentElement.classList.add('demo-pointer'); return;}
    if (data.action === 'prepare') {
      preparing = (async () => {
        reset(); const token = generation;
        await Promise.race([Promise.all([...$('#menu-view').querySelectorAll('img')].map(image => image.decode().catch(() => {}))),new Promise(resolve => setTimeout(resolve,1500))]);
        await nextPaint(); if (token === generation && runId === data.runId) notify('prepared');
      })();
      await preparing;
    }
    if (data.action === 'explore') {
      await preparing;
      if (runId === data.runId) {selectView('menu');scrollMenu(Math.max(20, Math.min(150,Number(data.speed) || 70)));}
    }
    if (data.action === 'locate-agent') {
      stopScroll(); window.scrollTo(0,0); await nextPaint();
      if (runId !== data.runId) return;
      const box = $('#agent-tab').getBoundingClientRect(); notify('agent-position', {agentRect:{x:box.x,y:box.y,width:box.width,height:box.height}});
    }
    if (data.action === 'recommend') {stopScroll(); selectView('agent'); await nextPaint(); if (runId === data.runId) notify('recommend-ready');}
    if (data.action === 'prompt') sendPrompt(String(data.text || 'Recommend dinner for two'));
    if (data.action === 'play-flow') window.MaisonShowcaseFlows?.play(data.flow, data.runId);
  });
  window.addEventListener('keydown', event => {
    if (!embedded || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest('input,textarea,select,[contenteditable=true]') || $('.dish-dialog').open) return;
    if (['ArrowRight','PageDown',' ','ArrowLeft','PageUp'].includes(event.key)) {event.preventDefault(); notify(['ArrowLeft','PageUp'].includes(event.key) ? 'navigate-back' : 'navigate-next');}
  });
  for (const type of ['wheel','pointerdown']) window.addEventListener(type, () => {if (scrollFrame !== null) {stopScroll(); notify('interrupted');}}, {passive:true});
  window.MaisonShowcase = {reset, sendPrompt, selectView, prepareFlow, stopWork, get busy(){return busy;}, notify,
    startNarrationClock,get narrationTime(){return narrationTime();},get narrationDuration(){return narrationClock?.duration||0;},
    setRunId(value){runId=value;},
    startExplore(){reset();exploreAudioMode=new URLSearchParams(location.hash.slice(1)).get('timing')==='audio';if(exploreAudioMode)startNarrationClock('explore');const token=generation;requestAnimationFrame(()=>requestAnimationFrame(()=>{if(token===generation){if(exploreAudioMode)scrollExploreNarration();else scrollMenu(70);}}));}
  };
  renderMenu(); notify('ready',{flowsReady:false});
})();

/* Excel-style column filters — używaj przez initExcelFilters('tableId') */
(function(){

function buildFilter(th, colIdx, tableId){
  th.style.position='relative';
  th.style.cursor='default';
  th.style.userSelect='none';

  const btn = document.createElement('span');
  btn.className='xf-btn';
  btn.innerHTML='&#9660;';
  btn.title='Filtruj';
  th.appendChild(btn);

  const panel = document.createElement('div');
  panel.className='xf-panel';
  panel.innerHTML=`
    <div class="xf-search"><input type="text" placeholder="Szukaj..." class="xf-sinp"></div>
    <div class="xf-actions">
      <button class="xf-all">Zaznacz wszystko</button>
      <button class="xf-none">Odznacz</button>
    </div>
    <div class="xf-list"></div>
    <div class="xf-footer">
      <button class="xf-ok btn-ok-xf">OK</button>
      <button class="xf-cancel">Anuluj</button>
    </div>`;
  document.body.appendChild(panel);

  let checked = new Set();
  let allVals  = [];

  function getVals(){
    const tbl = document.getElementById(tableId);
    if(!tbl) return [];
    const vals = new Set();
    tbl.querySelectorAll('tbody tr:not(.xf-hidden-row)').forEach(tr=>{
      const cell = tr.cells[colIdx];
      if(cell) vals.add(cell.textContent.trim());
    });
    // też dodaj wiersze ukryte przez TEN filtr żeby można było je odkryć
    tbl.querySelectorAll('tbody tr').forEach(tr=>{
      const cell = tr.cells[colIdx];
      if(cell) vals.add(cell.textContent.trim());
    });
    return [...vals].filter(Boolean).sort();
  }

  function buildList(filter=''){
    const list = panel.querySelector('.xf-list');
    list.innerHTML='';
    allVals.forEach(v=>{
      if(filter && !v.toLowerCase().includes(filter.toLowerCase())) return;
      const lbl = document.createElement('label');
      lbl.className='xf-item';
      const cb = document.createElement('input');
      cb.type='checkbox';
      cb.value=v;
      cb.checked=checked.has(v)||checked.size===0;
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(' '+v));
      list.appendChild(lbl);
    });
  }

  function openPanel(){
    // Zamknij inne panele
    document.querySelectorAll('.xf-panel.open').forEach(p=>{ if(p!==panel) p.classList.remove('open'); });
    allVals = getVals();
    if(checked.size===0) checked = new Set(allVals);
    buildList();
    const rect = btn.getBoundingClientRect();
    panel.style.top  = (rect.bottom + window.scrollY + 2)+'px';
    panel.style.left = (rect.left   + window.scrollX)+'px';
    panel.classList.toggle('open');
  }

  btn.addEventListener('click', e=>{ e.stopPropagation(); openPanel(); });

  panel.querySelector('.xf-sinp').addEventListener('input', e=>buildList(e.target.value));
  panel.querySelector('.xf-all').addEventListener('click',()=>{
    panel.querySelectorAll('.xf-item input').forEach(cb=>cb.checked=true);
  });
  panel.querySelector('.xf-none').addEventListener('click',()=>{
    panel.querySelectorAll('.xf-item input').forEach(cb=>cb.checked=false);
  });
  panel.querySelector('.xf-cancel').addEventListener('click',()=>panel.classList.remove('open'));
  panel.querySelector('.xf-ok').addEventListener('click',()=>{
    checked = new Set([...panel.querySelectorAll('.xf-item input:checked')].map(cb=>cb.value));
    panel.classList.remove('open');
    applyFilters(tableId);
  });
}

function applyFilters(tableId){
  const tbl = document.getElementById(tableId);
  if(!tbl) return;
  const panels = [...document.querySelectorAll('.xf-panel')];
  tbl.querySelectorAll('tbody tr').forEach(tr=>{
    let show=true;
    panels.forEach((p,colIdx)=>{
      const checked=[...p.querySelectorAll('.xf-item input:checked')].map(cb=>cb.value);
      if(checked.length===0) return; // brak filtra
      const cell=tr.cells[colIdx];
      if(!cell) return;
      if(!checked.includes(cell.textContent.trim())) show=false;
    });
    tr.classList.toggle('xf-hidden-row', !show);
    tr.style.display=show?'':'none';
  });
  // update liczniki
  tbl.querySelectorAll('.xf-count').forEach(el=>{
    const visible=tbl.querySelectorAll('tbody tr:not(.xf-hidden-row)').length;
    el.textContent=visible+' wierszy';
  });
}

window.initExcelFilters = function(tableId, colIndices){
  const tbl = document.getElementById(tableId);
  if(!tbl) return;
  // Usuń stare panele powiązane z tą tabelą
  document.querySelectorAll('.xf-panel[data-tbl="'+tableId+'"]').forEach(p=>p.remove());
  const ths = tbl.querySelectorAll('thead tr:first-child th');
  colIndices.forEach(idx=>{
    if(ths[idx]) buildFilter(ths[idx], idx, tableId);
  });
};

// Zamknij panele przy kliknięciu poza nimi
document.addEventListener('click', ()=>{
  document.querySelectorAll('.xf-panel.open').forEach(p=>p.classList.remove('open'));
});

})();

'use strict';
// Small, optional form pickers. Values keep the existing ID / ISO-date API contract.
const formPickers=(()=>{
  function utcDate(year,month,day=1){const d=new Date(0);d.setUTCFullYear(year,month-1,day);d.setUTCHours(0,0,0,0);return d;}
  function iso(year,month,day){return String(year).padStart(4,'0')+'-'+String(month).padStart(2,'0')+'-'+String(day).padStart(2,'0');}
  function parts(value){const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(value||'');if(!m)return null;const [year,month,day]=m.slice(1).map(Number);if(year<1||year>9999||month<1||month>12||day<1||day>days(year,month))return null;return {year,month,day};}
  function days(year,month){return utcDate(year,month+1,0).getUTCDate();}
  function weekday(year,month){return (utcDate(year,month).getUTCDay()+6)%7;}
  function today(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
  function button(text,cls,action,label){const b=el('button',cls,text);b.type='button';if(label)b.setAttribute('aria-label',label);b.onclick=action;return b;}
  function open(field,value){return new Promise(resolve=>{
    const sheet=el('dialog','field-sheet');sheet.setAttribute('aria-modal','true');const title=el('h2','','选择'+field.label);title.id='field-picker-title';sheet.setAttribute('aria-labelledby',title.id);
    const head=el('div','picker-heading');head.append(title,button('×','picker-close',()=>sheet.close(),'关闭选择面板'));
    const body=el('div','picker-body');sheet.append(el('div','sheet-handle'),head,body);let answer=null;
    function choose(next){answer=next;sheet.close();}
    sheet.addEventListener('click',event=>{if(event.target===sheet){const r=sheet.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)sheet.close();}});
    sheet.addEventListener('close',()=>{sheet.remove();resolve(answer);},{once:true});
    if(field.type==='select'){
      const hint=el('p','picker-hint','选择后立即填入表单，提交表单后才发送。');body.append(hint);
      const choices=el('div','picker-options');choices.setAttribute('role','group');choices.setAttribute('aria-label',field.label);
      for(const option of field.options){const b=button('','picker-option'+(value===option.id?' chosen':''),()=>choose(option.id));b.setAttribute('aria-pressed',String(value===option.id));b.append(el('span','',option.label),el('span','picker-check',value===option.id?'✓':''));choices.append(b);}
      body.append(choices);const footer=el('div','picker-footer');footer.append(button('清空','picker-secondary',()=>choose('')),button('取消','picker-secondary',()=>sheet.close()));body.append(footer);
    }else{
      const current=today(),initial=parts(value)||parts(current);let year=initial.year,month=initial.month,selected=parts(value)?value:'',view='days',yearStart=Math.max(1,year-7);
      const chosen=el('div','calendar-selection');const selectedText=el('span');selectedText.setAttribute('role','status');chosen.append(selectedText,button('今天','picker-today',()=>{const d=parts(current);year=d.year;month=d.month;selected=current;view='days';render();}));body.append(chosen);
      const panel=el('div','calendar-panel');body.append(panel);const footer=el('div','picker-footer');const confirm=button('确定日期','picker-primary',()=>choose(selected));footer.append(button('清空','picker-secondary',()=>choose('')),confirm);body.append(footer);
      function shift(delta){if(view==='years'){yearStart=Math.min(9980,Math.max(1,yearStart+delta*20));}else if(view==='months'){year=Math.min(9999,Math.max(1,year+delta));}else{const total=(year-1)*12+month-1+delta;if(total<0||total>=9999*12)return;year=Math.floor(total/12)+1;month=total%12+1;}render();panel.querySelector(delta<0?'.calendar-arrow:first-child':'.calendar-arrow:last-child')?.focus();}
      function render(){
        selectedText.textContent=selected?selected.replace(/^(\d+)-(\d+)-(\d+)$/,'$1 年 $2 月 $3 日'):'尚未选择日期';confirm.disabled=!selected;
        panel.replaceChildren();const nav=el('div','calendar-nav');const heading=view==='years'?yearStart+'–'+Math.min(9999,yearStart+19)+' 年':view==='months'?year+' 年':year+' 年 '+month+' 月';
        function focusView(){panel.querySelector('.calendar-unit.chosen,.calendar-month')?.focus();}
        const center=button(heading,'calendar-month',()=>{view=view==='days'?'years':'days';yearStart=Math.min(9980,Math.max(1,year-7));render();focusView();},'选择年份月份：'+heading);
        const arrow=el('span','field-chevron');arrow.setAttribute('aria-hidden','true');center.setAttribute('aria-expanded',String(view!=='days'));center.append(arrow);
        nav.append(button('‹','calendar-arrow',()=>shift(-1),view==='years'?'前二十年':view==='months'?'上一年':'上个月'),center,button('›','calendar-arrow',()=>shift(1),view==='years'?'后二十年':view==='months'?'下一年':'下个月'));panel.append(nav);
        if(view==='years'){const grid=el('div','calendar-years');for(let y=yearStart;y<=Math.min(9999,yearStart+19);y++){const b=button(String(y),'calendar-unit'+(y===year?' chosen':''),()=>{year=y;view='months';render();focusView();});grid.append(b);}panel.append(grid);return;}
        if(view==='months'){const grid=el('div','calendar-months');for(let m=1;m<=12;m++){const b=button(m+' 月','calendar-unit'+(m===month?' chosen':''),()=>{month=m;view='days';render();focusView();});grid.append(b);}panel.append(grid);return;}
        const weeks=el('div','calendar-weekdays');for(const day of ['一','二','三','四','五','六','日'])weeks.append(el('span','',day));panel.append(weeks);
        const grid=el('div','calendar-days');grid.setAttribute('role','group');grid.setAttribute('aria-label',year+'年'+month+'月');for(let n=0;n<weekday(year,month);n++)grid.append(el('span','calendar-empty'));
        for(let d=1;d<=days(year,month);d++){const date=iso(year,month,d),b=button(String(d),'calendar-day'+(date===selected?' chosen':'')+(date===current?' today':''),()=>{selected=date;render();panel.querySelector('[data-date="'+date+'"]')?.focus();},year+'年'+month+'月'+d+'日');b.dataset.date=date;b.setAttribute('aria-pressed',String(date===selected));if(date===current)b.setAttribute('aria-current','date');grid.append(b);}panel.append(grid);
      }
      render();
    }
    document.body.append(sheet);sheet.showModal();
  });}
  return {open,parts,days,weekday,iso};
})();

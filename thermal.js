(() => {
  'use strict';

  const seasons = ['#246e9d', '#bb4b54', '#328478', '#7955a3', '#2c456a', '#b9651a', '#6e7b3e', '#7b5862'];
  const palette = ['#226d70', '#d16439', '#387bb0', '#8762a5', '#7e8847', '#ad416d', '#765747'];
  const dayMs = 86400000;
  const seasonStart = Date.UTC(2000, 0, 1);
  const frequencies = { daily: '日度', weekly: '周度', tenDay: '旬度', monthly: '月度', ytd: '月度累计' };
  const qualityLabels = {
    estimated: '原表分摊/推算', combined: '1–2 月合计', coverage: '分港覆盖未确认', missing: '源值缺失',
    'excel-error': 'Excel 源值错误', placeholder: '源值为占位',
  };
  const compareLabels = {
    'no-base': '无对应基期', missing: '本期无有效值', 'year-reset': '年初重新累计',
    'nonpositive-base': '基期非正值', 'different-period': '基期统计区间不同',
  };
  const at = id => document.getElementById(id);
  const numeric = value => typeof value === 'number' && Number.isFinite(value);
  const monthStart = month => Date.UTC(2000, month - 1, 1);
  const weekPosition = time => Math.floor((time - seasonStart) / (dayMs * 7));
  const dateParts = date => date.split('-').map(Number);
  const tenDayIndex = day => day <= 10 ? 0 : day <= 20 ? 1 : 2;

  function seasonalTime(date, frequency) {
    const [, month, day] = dateParts(date);
    if (frequency === 'monthly' || frequency === 'ytd') return monthStart(month);
    if (frequency === 'tenDay') {
      const endOfMonth = new Date(Date.UTC(2000, month, 0)).getUTCDate();
      return Date.UTC(2000, month - 1, Math.min([10, 20, 30][tenDayIndex(day)], endOfMonth));
    }
    return Date.UTC(2000, month - 1, day);
  }

  function isGap(previous, current, series) {
    if (!previous) return false;
    const days = (Date.parse(current) - Date.parse(previous)) / dayMs;
    if (series.frequency === 'daily') return days > (series.cadence === 'market' ? 7 : 1);
    if (series.frequency === 'weekly') {
      const week = date => {
        const time = Date.parse(date);
        return time - ((new Date(time).getUTCDay() + 6) % 7) * dayMs;
      };
      return week(current) - week(previous) > 7 * dayMs;
    }
    const [year, month, day] = dateParts(current);
    const [lastYear, lastMonth, lastDay] = dateParts(previous);
    const months = (year - lastYear) * 12 + month - lastMonth;
    if (series.frequency === 'tenDay') return months * 3 + tenDayIndex(day) - tenDayIndex(lastDay) > 1;
    return months > 1;
  }

  function periodLabel(date, frequency) {
    if (frequency === 'monthly' || frequency === 'ytd') return date.slice(0, 7);
    if (frequency === 'tenDay') return `${date.slice(0, 7)} ${['上旬', '中旬', '下旬'][tenDayIndex(Number(date.slice(8)))]}`;
    return date;
  }

  window.initThermalDashboard = ({ data: thermalData, cokingData, loadFailures = {}, renderPlot, node, timestamp, iso, number, renderOverview }) => {
    const view = at('thermal-view');
    const plot = at('thermal-plot');
    const chartCard = at('thermal-card');
    const seriesCache = new Map();
    const panelState = new Map();
    const panelByGroup = new Map();
    const topics = {
      thermal: { label: '动力煤', dataset: thermalData, loadFailure: loadFailures.thermalCoal,
        mode: { seasonal: false, monthStart: 1, monthEnd: 12 } },
      coking: { label: '炼焦煤', dataset: cokingData, loadFailure: loadFailures.cokingCoal,
        mode: { seasonal: false, monthStart: 1, monthEnd: 12 } },
    };
    let topic, data, mode, currentGroup, currentPanel, resizeTimer;

    const groupKey = () => `${topic}/${currentGroup.id}`;
    const panelKey = () => `${groupKey()}/${currentPanel.id}`;

    function current() {
      return panelState.get(panelKey());
    }

    function getSeries(id) {
      const cacheKey = `${topic}/${id}`;
      if (!seriesCache.has(cacheKey)) {
        const series = data.series[id];
        let previous;
        const decode = ([value, base, status, estimated, absolute]) => [value, data.dates[base], status, estimated, absolute];
        const points = series.points.map(([dateIndex, value, mom, yoy, quality]) => {
          const date = data.dates[dateIndex];
          const point = { date, value, mom: decode(mom), yoy: decode(yoy), quality, time: timestamp(date),
            breakBefore: isGap(previous, date, series) };
          previous = date;
          return point;
        });
        const years = [...new Set(points.filter(point => numeric(point.value)).map(point => Number(point.date.slice(0, 4))))];
        seriesCache.set(cacheKey, { ...series, points, years });
      }
      return seriesCache.get(cacheKey);
    }

    function setPreset(preset) {
      const state = current();
      const selected = currentPanel.seriesIds.filter(id => !state.hidden.has(id)).map(id => data.series[id]);
      const available = selected.filter(series => series.latestValidDate);
      const latest = available.map(series => series.latestValidDate).sort().pop();
      const earliest = available.map(series => series.firstValidDate).sort()[0];
      state.preset = preset;
      if (!latest) return;
      if (preset === 'all') {
        state.start = earliest;
        state.end = latest;
        return;
      }
      const [year, month, day] = dateParts(latest);
      const targetYear = year - Number(preset);
      const dayLimit = new Date(Date.UTC(targetYear, month, 0)).getUTCDate();
      const begin = iso(Date.UTC(targetYear, month - 1, Math.min(day, dayLimit)));
      state.start = begin < earliest ? earliest : begin;
      state.end = latest;
    }

    function groupButtons(groups) {
      for (const group of groups) {
        const link = node('a', '', group.name);
        link.href = `#${topic}/${group.id}`;
        if (group === currentGroup) link.setAttribute('aria-current', 'true');
        at('thermal-groups').append(link);
      }
    }

    function selectPanel(panel) {
      currentPanel = panel;
      panelByGroup.set(groupKey(), panel.id);
      const key = panelKey();
      if (!panelState.has(key)) {
        const available = panel.seriesIds.find(id => data.series[id].latestValidDate) ?? panel.seriesIds[0];
        panelState.set(key, { hidden: new Set(), selected: available, years: new Map(), start: '', end: '' });
        setPreset('1');
      }
      at('thermal-panel').value = panel.id;
      render();
    }

    function options(select, items, selected) {
      select.replaceChildren(...items.map(([key, label]) => {
        const option = node('option', '', label);
        option.value = key;
        return option;
      }));
      if (selected != null) select.value = selected;
    }

    function updateRoute() {
      const route = /^#(thermal|coking)(?:\/([a-z0-9-]+))?$/.exec(window.location.hash);
      const showDetails = Boolean(route);
      view.hidden = !showDetails;
      at('overview-view').hidden = showDetails;
      at('overview-nav').hidden = showDetails;
      const active = route?.[1] ?? 'overview';
      for (const section of ['overview', 'thermal', 'coking']) {
        const link = at(`view-${section}`);
        if (section === active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }
      if (!showDetails) {
        renderOverview();
        return;
      }
      topic = route[1];
      const entry = topics[topic];
      data = entry.dataset;
      mode = entry.mode;
      const groups = data?.groups ?? [];
      const groupNav = at('thermal-groups');
      at('thermal-title').textContent = entry.label;
      groupNav.setAttribute('aria-label', `${entry.label}图表分组`);
      groupNav.replaceChildren();
      at('thermal-unavailable').hidden = Boolean(groups.length);
      chartCard.hidden = !groups.length;
      if (!groups.length) {
        currentGroup = currentPanel = null;
        at('thermal-unavailable').textContent = entry.loadFailure
          ? `${entry.label}明细加载失败，请刷新后重试。`
          : `当前数据文件未包含${entry.label}明细。运行更新脚本生成新版 data.js 后即可查看。`;
        return;
      }
      currentGroup = groups.find(group => group.id === route[2]) ?? groups[0];
      groupButtons(groups);
      options(at('thermal-panel'), currentGroup.panels.map(panel => [panel.id, panel.name]));
      selectPanel(currentGroup.panels.find(panel => panel.id === panelByGroup.get(groupKey())) ?? currentGroup.panels[0]);
    }

    function seasonalYears(series, state) {
      if (!state.years.has(series.id)) state.years.set(series.id, new Set(series.years.slice(-6)));
      return state.years.get(series.id);
    }

    function colorForYear(year, years) {
      return seasons[years.indexOf(year) % seasons.length];
    }

    function updateControls(activeSeries) {
      const state = current();
      at('thermal-continuous').setAttribute('aria-pressed', String(!mode.seasonal));
      at('thermal-seasonal').setAttribute('aria-pressed', String(mode.seasonal));
      at('thermal-series-field').hidden = !mode.seasonal;
      at('thermal-date-filter').hidden = mode.seasonal;
      at('thermal-season-filter').hidden = !mode.seasonal;
      at('thermal-start').value = state.start;
      at('thermal-end').value = state.end;
      at('thermal-date-error').hidden = true;
      at('thermal-month-error').hidden = true;
      for (const button of at('thermal-presets').querySelectorAll('button')) {
        const selected = state.preset === button.dataset.range;
        button.setAttribute('aria-pressed', String(selected));
        button.classList.toggle('selected', selected);
      }
      if (!mode.seasonal) return;
      options(at('thermal-series'), currentPanel.seriesIds.map(id => [id, data.series[id].name]), state.selected);
      for (const [suffix, month] of [['start', mode.monthStart], ['end', mode.monthEnd]]) {
        at(`thermal-month-${suffix}`).value = month;
      }
      const years = seasonalYears(activeSeries, state);
      at('thermal-years').replaceChildren(...activeSeries.years.map(year => {
        const label = node('label', 'thermal-year');
        const check = node('input');
        const swatch = node('span', 'legend-swatch');
        check.type = 'checkbox';
        check.checked = years.has(year);
        swatch.style.backgroundColor = colorForYear(year, activeSeries.years);
        check.addEventListener('change', () => {
          if (check.checked) years.add(year); else years.delete(year);
          draw();
        });
        label.append(check, swatch, node('span', '', String(year)));
        return label;
      }));
    }

    function legend() {
      at('thermal-legend').replaceChildren();
      if (mode.seasonal) return;
      const state = current();
      currentPanel.seriesIds.forEach((id, index) => {
        const series = data.series[id];
        const button = node('button', 'legend-button');
        const swatch = node('span', 'legend-swatch');
        button.type = 'button';
        button.setAttribute('aria-pressed', String(!state.hidden.has(id)));
        swatch.style.backgroundColor = palette[index % palette.length];
        button.append(swatch, node('span', '', series.name));
        button.addEventListener('click', () => {
          if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
          if (state.hidden.has(state.selected)) {
            state.selected = currentPanel.seriesIds.find(seriesId => !state.hidden.has(seriesId)) ?? state.selected;
          }
          button.setAttribute('aria-pressed', String(!state.hidden.has(id)));
          if (state.preset) {
            setPreset(state.preset);
            at('thermal-start').value = state.start;
            at('thermal-end').value = state.end;
          }
          draw();
        });
        at('thermal-legend').append(button);
      });
    }

    function render() {
      if (!currentPanel) return;
      const selected = getSeries(current().selected);
      updateControls(selected);
      legend();
      at('thermal-chart-name').textContent = `${currentGroup.name} · ${currentPanel.name}`;
      at('thermal-chart-note').textContent = currentPanel.note;
      at('thermal-chart-note').hidden = !currentPanel.note;
      at('thermal-unit').textContent = `${frequencies[selected.frequency]} · ${selected.unit}`;
      draw();
    }

    function formatValue(value, unit) {
      return unit === '%' && numeric(value) ? `${number(value * 100)}%` : number(value);
    }

    function comparisonText(change, series) {
      const [value, base, status, estimated, absolute] = change;
      if (!numeric(value)) {
        const difference = numeric(absolute) ? `，差额 ${number(absolute)} ${series.unit}` : '';
        return `—（${compareLabels[status] ?? '无对应期'}${base ? `，${base}` : ''}${difference}）`;
      }
      const unit = series.changeUnit === 'pp' ? ' 个百分点' : series.changeUnit === '%' ? '%' : ` ${series.unit}`;
      const display = series.changeUnit === 'absolute' ? value : value * 100;
      const method = status === 'reported' ? '原表' : '计算';
      const baseNote = base ? `${method}，基期 ${base}` : `${method}，基期未列明`;
      return `${display > 0 ? '+' : ''}${number(display)}${unit}（${baseNote}${estimated ? '，基期含分摊' : ''}）`;
    }

    function plotTooltip(tooltip, seriesList, dates, time) {
      const title = at('thermal-chart-name').textContent;
      const fragment = document.createDocumentFragment();
      const frequency = seriesList[0].frequency;
      const heading = mode.seasonal
        ? (frequency === 'monthly' || frequency === 'ytd'
          ? `${new Date(time).getUTCMonth() + 1}月`
          : frequency === 'tenDay' ? periodLabel(iso(time), frequency).slice(5) : iso(time).slice(5).replace('-', '月') + '日')
        : periodLabel(iso(time), frequency);
      fragment.append(node('time', '', heading));
      for (const [index, series] of seriesList.entries()) {
        let point = dates[index].get(time);
        if (!point && mode.seasonal && series.frequency === 'weekly') {
          point = dates[index].get(series.byWeek.get(weekPosition(time)));
        }
        const section = node('div', 'thermal-tip-row');
        const label = series.year ? `${series.year} · ${series.name}` : series.name;
        const row = node('div', 'tooltip-row');
        const value = point && numeric(point.value)
          ? `${formatValue(point.value, series.unit)}${series.unit === '%' ? '' : ` ${series.unit}`}`
          : '—';
        row.append(node('strong', '', label), node('strong', '', value));
        section.append(row);
        if (point) {
          const period = periodLabel(point.date, series.frequency);
          section.append(node('small', '', `${period}${point.quality ? ` · ${qualityLabels[point.quality]}` : ''}`));
          if (numeric(point.value)) {
            const mom = series.frequency === 'ytd' ? '累计较上月' : '环比';
            section.append(node('small', '', `${mom} ${comparisonText(point.mom, series)}`),
                           node('small', '', `同比 ${comparisonText(point.yoy, series)}`));
          }
        } else section.append(node('small', '', '该期无数据'));
        fragment.append(section);
      }
      tooltip.classList.add('thermal-tooltip');
      tooltip.setAttribute('aria-label', title);
      tooltip.replaceChildren(fragment);
    }

    function seriesForYear(series, year) {
      const points = series.points.filter(point => Number(point.date.slice(0, 4)) === year)
        .map(point => ({ ...point, time: seasonalTime(point.date, series.frequency) }));
      const byWeek = series.frequency === 'weekly'
        ? new Map(points.map(point => [weekPosition(point.time), point.time]))
        : new Map();
      return { ...series, data: points, byWeek, year, color: colorForYear(year, series.years) };
    }

    function draw() {
      if (!currentPanel || view.hidden) return;
      const state = current();
      const selected = getSeries(state.selected);
      const used = mode.seasonal ? [selected] : currentPanel.seriesIds.filter(id => !state.hidden.has(id)).map(getSeries);
      at('thermal-sources').replaceChildren(...used.map(series => {
        const columns = series.source.valueColumns.join('、');
        const latest = series.latestValidDate ? periodLabel(series.latestValidDate, series.frequency) : '无有效数据';
        return node('li', '', `${series.name} · 最新统计期 ${latest} · ${series.source.sheet} / ${series.source.dateColumn} → ${columns}`);
      }));
      if (!used.length || (!mode.seasonal && !state.start) || (mode.seasonal && !seasonalYears(selected, state).size)) {
        plot.replaceChildren(node('div', 'plot-empty', mode.seasonal ? '请选择有数据的年份' : '请选择有有效数据的序列'));
        return;
      }
      const series = mode.seasonal
        ? [...seasonalYears(selected, state)].sort().map(year => seriesForYear(selected, year))
        : used.map(item => ({ ...item, data: item.points, color: palette[currentPanel.seriesIds.indexOf(item.id) % palette.length] }));
      const bounds = mode.seasonal
        ? [monthStart(mode.monthStart), monthStart(mode.monthEnd + 1) - dayMs]
        : [timestamp(state.start), timestamp(state.end)];
      const span = (bounds[1] - bounds[0]) / dayMs;
      const ticks = width => {
        if (mode.seasonal) return Array.from({ length: mode.monthEnd - mode.monthStart + 1 }, (_, index) => mode.monthStart + index)
          .filter((_, index) => width >= 450 || index % 2 === 0)
          .map(month => [monthStart(month), `${month}月`]);
        if (span < 1) return [[bounds[0], state.start]];
        const count = Math.min(width < 430 ? 3 : 6, Math.floor(span) + 1);
        return Array.from({ length: count }, (_, index) => {
          const time = bounds[0] + (bounds[1] - bounds[0]) * index / (count - 1);
          return [time, span <= 45 ? iso(time).slice(5) : iso(time).slice(0, 7)];
        });
      };
      renderPlot({ title: at('thermal-chart-name').textContent, unit: selected.unit }, plot, {
        series, bounds, ticks, fillTooltip: plotTooltip,
        formatValue: value => formatValue(value, selected.unit),
        rangeLabel: mode.seasonal ? `${mode.monthStart}月至${mode.monthEnd}月` : `${state.start}至${state.end}`,
      });
    }

    function errorMessage(id, text) {
      const message = at(id);
      message.textContent = text;
      message.hidden = !text;
    }

    at('thermal-panel').addEventListener('change', event => {
      const next = currentGroup.panels.find(panel => panel.id === event.target.value);
      if (next) selectPanel(next);
    });
    at('thermal-series').addEventListener('change', event => {
      const state = current();
      state.selected = event.target.value;
      state.hidden.delete(state.selected);
      if (state.preset) setPreset(state.preset);
      render();
    });
    at('thermal-continuous').addEventListener('click', () => { mode.seasonal = false; render(); });
    at('thermal-seasonal').addEventListener('click', () => { mode.seasonal = true; render(); });
    at('thermal-presets').addEventListener('click', event => {
      const preset = event.target.closest('button')?.dataset.range;
      if (preset) {
        setPreset(preset);
        render();
      }
    });
    at('thermal-date-filter').addEventListener('submit', event => {
      event.preventDefault();
      const start = at('thermal-start').value;
      const end = at('thermal-end').value;
      if (!start || !end || start > end) {
        errorMessage('thermal-date-error', '开始日期不能晚于结束日期。');
        return;
      }
      Object.assign(current(), { start, end, preset: '' });
      render();
    });
    const months = Array.from({ length: 12 }, (_, index) => [index + 1, `${index + 1} 月`]);
    options(at('thermal-month-start'), months, 1);
    options(at('thermal-month-end'), months, 12);
    at('thermal-season-filter').addEventListener('submit', event => {
      event.preventDefault();
      const monthStartValue = Number(at('thermal-month-start').value);
      const monthEndValue = Number(at('thermal-month-end').value);
      if (monthStartValue > monthEndValue) {
        errorMessage('thermal-month-error', '起始月不能晚于结束月。');
        return;
      }
      Object.assign(mode, { monthStart: monthStartValue, monthEnd: monthEndValue });
      errorMessage('thermal-month-error', '');
      draw();
    });
    window.addEventListener('hashchange', updateRoute);
    new ResizeObserver(() => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(draw, 100);
    }).observe(plot);
    updateRoute();
  };
})();

(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const number = value => finite(value)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value) : '—';
  const iso = milliseconds => new Date(milliseconds).toISOString().slice(0, 10);
  const timestamp = text => Date.parse(`${text}T00:00:00Z`);
  const svgNode = (tag, attributes = {}, text) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  };

  try {
    const data = window.COAL_DATA;
    if (!data || !data.meta || !Array.isArray(data.charts) || !Array.isArray(data.weeklyMetrics)) {
      throw new Error('未能加载看板数据。请确认 data.js 与 index.html 位于同一文件夹，再刷新页面。');
    }
    const state = { section: '全部', search: '', start: '', end: data.meta.databaseDate };
    const latest = timestamp(data.meta.databaseDate);
    const earliest = Math.min(...data.charts.flatMap(chart => chart.series.flatMap(series =>
      series.data.length ? [timestamp(series.data[0].date)] : [])));
    const hiddenSeries = new Map();
    const charts = new Map();

    $('#database-date').textContent = data.meta.databaseDate;
    $('#weekly-date').textContent = data.meta.weeklyDate;
    $('#source-name').textContent = data.meta.source;
    $('#generated-at').textContent = `数据生成于 ${data.meta.generatedAt.replace('T', ' ')}（北京时间）`;

    function valueText(metric, value) {
      if (!finite(value)) return '—';
      return number(metric.valueIsFraction ? value * 100 : value);
    }

    function changeText(metric, field = 'wow') {
      const value = metric[field];
      if (!finite(value)) return '—';
      const points = metric.changeType === 'percentagePoints';
      const adjusted = Math.abs(value) < 1e-8 ? 0 : value * (points ? 1 : 100);
      return `${adjusted > 0 ? '+' : ''}${adjusted.toFixed(2)}${points ? ' 个百分点' : '%'}`;
    }

    function changeNode(metric, field = 'wow') {
      const value = metric[field];
      return node('span', `change ${!finite(value) || value === 0 ? 'flat' : value > 0 ? 'up' : 'down'}`,
        changeText(metric, field));
    }

    data.summaryCards.forEach((metric, index) => {
      const card = node('article', 'summary-card');
      const label = node('p', 'card-label', metric.metric);
      label.append(node('span', '', String(index + 1).padStart(2, '0')));
      const value = node('div', 'card-number', valueText(metric, metric.current));
      value.append(node('small', '', metric.unit));
      const foot = node('div', 'card-foot');
      foot.append(node('span', '', '较前期'), changeNode(metric));
      card.append(label, value, foot);
      $('#summary-cards').append(card);
    });

    if (data.warnings?.length) {
      $('#quality-notes').hidden = false;
      $('#quality-summary').textContent = `数据覆盖与缺失说明（${data.warnings.length} 条）`;
      data.warnings.forEach(warning => $('#quality-list').append(node('li', '', warning.message)));
      $('#quality-notes').addEventListener('toggle', event => {
        $('.expand-label').textContent = event.target.open ? '收起说明' : '展开查看';
      });
    }

    function selectRange(years) {
      const date = new Date(latest);
      const candidate = years === 'all' ? earliest
        : Date.UTC(date.getUTCFullYear() - Number(years), date.getUTCMonth(), date.getUTCDate());
      state.start = iso(Math.max(candidate, earliest));
      state.end = data.meta.databaseDate;
      $('#start-date').value = state.start;
      $('#end-date').value = state.end;
      $('#date-error').hidden = true;
      $$('.range-buttons button').forEach(button => {
        const selected = button.dataset.years === String(years);
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
      });
      renderCharts();
    }

    function dateTicks(start, end, count) {
      if (start === end) return [start];
      return Array.from({ length: count }, (_, index) => start + (end - start) * index / (count - 1));
    }

    function nearestIndex(array, target) {
      let low = 0, high = array.length - 1;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (array[middle] < target) low = middle + 1;
        else high = middle;
      }
      return low > 0 && Math.abs(array[low - 1] - target) < Math.abs(array[low] - target) ? low - 1 : low;
    }

    function niceStep(span) {
      const rough = Math.max(span / 4, 0.000001);
      const magnitude = 10 ** Math.floor(Math.log10(rough));
      return ([1, 2, 2.5, 5, 10].find(value => value * magnitude >= rough) || 10) * magnitude;
    }

    function renderPlot(chart, plot) {
      plot.replaceChildren();
      const enabled = chart.series.filter(series => !hiddenSeries.get(chart.id).has(series.name));
      const start = timestamp(state.start), end = timestamp(state.end);
      const visible = enabled.map(series => ({ ...series,
        points: series.data.filter(point => point.time >= start && point.time <= end) }));
      const values = visible.flatMap(series => series.points.filter(point => finite(point.value)).map(point => point.value));
      if (!values.length) {
        plot.append(node('div', 'plot-empty', enabled.length ? '所选区间暂无有效数据' : '请选择至少一条序列'));
        return;
      }
      const width = Math.max(260, plot.clientWidth), height = plot.clientHeight || 244;
      const margin = { left: 51, right: 12, top: 13, bottom: 28 };
      const innerWidth = width - margin.left - margin.right;
      const innerHeight = height - margin.top - margin.bottom;
      const minimum = Math.min(...values), maximum = Math.max(...values);
      const span = maximum - minimum || Math.abs(maximum) * 0.1 || 1;
      const step = niceStep(span * 1.15);
      const axisMin = Math.max(0, Math.floor((minimum - span * 0.06) / step) * step);
      const axisMax = Math.ceil((maximum + span * 0.06) / step) * step;
      const x = value => margin.left + (value - start) / (end - start || 1) * innerWidth;
      const y = value => margin.top + (axisMax - value) / (axisMax - axisMin || 1) * innerHeight;
      const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', tabindex: '0',
        'aria-label': `${chart.title}，${state.start}至${state.end}，单位${chart.unit}。使用左右方向键查看日期数据。` });
      svg.append(svgNode('title', {}, `${chart.title}（${chart.unit}）`));
      for (let tick = axisMin; tick <= axisMax + step * 0.01; tick += step) {
        svg.append(svgNode('line', { x1: margin.left, x2: width - margin.right, y1: y(tick), y2: y(tick), class: 'grid-line' }));
        svg.append(svgNode('text', { x: margin.left - 10, y: y(tick) + 3, 'text-anchor': 'end' }, number(tick)));
      }
      dateTicks(start, end, width < 430 ? 3 : 5).forEach((tick, index, ticks) => {
        const label = iso(tick).slice(0, 7).replace('-', '.');
        svg.append(svgNode('text', { x: x(tick), y: height - 7,
          'text-anchor': index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle' }, label));
      });
      visible.forEach(series => {
        let path = '', drawing = false;
        series.points.forEach(point => {
          if (!finite(point.value)) { drawing = false; return; }
          path += `${drawing ? 'L' : 'M'}${x(point.time).toFixed(2)},${y(point.value).toFixed(2)} `;
          drawing = true;
        });
        svg.append(svgNode('path', { d: path, class: 'data-line', stroke: series.color }));
        const validPoints = series.points.filter(point => finite(point.value));
        if (validPoints.length === 1) svg.append(svgNode('circle', { cx: x(validPoints[0].time), cy: y(validPoints[0].value), r: 3, fill: series.color }));
      });
      const crosshair = svgNode('line', { x1: 0, x2: 0, y1: margin.top, y2: height - margin.bottom, class: 'crosshair', style: 'display:none' });
      svg.append(crosshair);
      const tooltip = node('div', 'plot-tooltip');
      tooltip.setAttribute('role', 'tooltip');
      const dates = [...new Set(visible.flatMap(series => series.points.map(point => point.time)))].sort((a, b) => a - b);
      const byDate = visible.map(series => new Map(series.points.map(point => [point.time, point.value])));
      let focusIndex = dates.length - 1;
      function showTooltip(index, pointerY = 30) {
        if (!dates.length) return;
        focusIndex = index;
        const day = dates[index], position = x(day);
        crosshair.style.display = '';
        crosshair.setAttribute('x1', position);
        crosshair.setAttribute('x2', position);
        tooltip.replaceChildren(node('time', '', iso(day)));
        visible.forEach((series, seriesIndex) => {
          const row = node('div', 'tooltip-row');
          row.append(node('span', '', series.name), node('strong', '', number(byDate[seriesIndex].get(day))));
          tooltip.append(row);
        });
        tooltip.style.display = 'block';
        tooltip.style.left = `${Math.max(4, Math.min(width - tooltip.offsetWidth - 4, position + 12))}px`;
        tooltip.style.top = `${Math.max(3, Math.min(height - tooltip.offsetHeight - 4, pointerY))}px`;
      }
      function hideTooltip() { tooltip.style.display = 'none'; crosshair.style.display = 'none'; }
      svg.addEventListener('pointermove', event => {
        const box = svg.getBoundingClientRect();
        const mouseX = (event.clientX - box.left) / box.width * width;
        if (mouseX < margin.left || mouseX > width - margin.right) { hideTooltip(); return; }
        const requested = start + (mouseX - margin.left) / innerWidth * (end - start);
        showTooltip(nearestIndex(dates, requested), event.clientY - box.top + 10);
      });
      svg.addEventListener('pointerleave', hideTooltip);
      svg.addEventListener('blur', hideTooltip);
      svg.addEventListener('keydown', event => {
        if (event.key === 'Escape') hideTooltip();
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault();
          tooltip.setAttribute('aria-live', 'polite');
          showTooltip(Math.max(0, Math.min(dates.length - 1, focusIndex + (event.key === 'ArrowLeft' ? -1 : 1))));
        }
      });
      plot.append(svg, tooltip);
    }

    data.charts.forEach(sourceChart => {
      const chart = { ...sourceChart, series: sourceChart.series.map(series => ({ ...series,
        color: /^#[0-9a-f]{6}$/i.test(series.color) ? series.color : '#226d70',
        data: series.data.map(point => ({ ...point, time: timestamp(point.date) })) })) };
      hiddenSeries.set(chart.id, new Set());
      const card = node('article', 'chart-card');
      card.id = `chart-${chart.id}`;
      const head = node('div', 'chart-header'), text = node('div');
      text.append(node('h3', '', chart.title), node('p', 'chart-subtitle', chart.subtitle));
      head.append(text, node('span', 'chart-unit', chart.unit));
      const legend = node('div', 'chart-legend');
      const plot = node('div', 'plot');
      chart.series.forEach(series => {
        const button = node('button', 'legend-button');
        button.type = 'button';
        button.setAttribute('aria-pressed', 'true');
        button.setAttribute('aria-label', `显示${series.name}`);
        const swatch = node('span', 'legend-swatch');
        swatch.style.background = series.color;
        button.append(swatch, node('span', '', series.name));
        button.addEventListener('click', () => {
          const hidden = hiddenSeries.get(chart.id);
          if (hidden.has(series.name)) hidden.delete(series.name); else hidden.add(series.name);
          button.setAttribute('aria-pressed', String(!hidden.has(series.name)));
          renderPlot(chart, plot);
        });
        legend.append(button);
      });
      const foot = node('div', 'chart-foot');
      const endDates = chart.series.map(series => series.dateRange?.last).filter(Boolean).sort();
      const coverage = endDates[0] === endDates[endDates.length - 1] ? endDates[0] : `${endDates[0]} 至 ${endDates[endDates.length - 1]}`;
      foot.append(node('span', '', `源数据最新日期：${coverage}`), node('span', '', `${chart.frequency || ''}数据 · 悬停查看`));
      card.append(head, legend, plot, foot);
      $('#charts').append(card);
      charts.set(chart.id, { chart, plot });
    });

    function renderCharts() { charts.forEach(({ chart, plot }) => renderPlot(chart, plot)); }
    let resizeTimer;
    const observer = new ResizeObserver(() => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(renderCharts, 100);
    });
    observer.observe($('#charts'));
    const sections = ['全部', ...new Set(data.weeklyMetrics.map(metric => metric.section))];
    sections.forEach(section => {
      const button = node('button', section === '全部' ? 'active' : '', section);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(section === '全部'));
      button.addEventListener('click', () => {
        state.section = section;
        $$('#section-tabs button').forEach(item => {
          item.classList.toggle('active', item === button);
          item.setAttribute('aria-pressed', String(item === button));
        });
        renderTable();
      });
      $('#section-tabs').append(button);
    });

    function selectedMetrics() {
      const search = state.search.trim().toLocaleLowerCase();
      return data.weeklyMetrics.filter(metric => (state.section === '全部' || metric.section === state.section)
        && [metric.metric, metric.unit, metric.group, metric.section, metric.note].join(' ').toLocaleLowerCase().includes(search));
    }

    function renderTable() {
      const metrics = selectedMetrics(), body = $('#metrics-body');
      body.replaceChildren();
      metrics.forEach(metric => {
        const row = node('tr');
        row.dataset.metric = metric.metric;
        const label = node('td');
        label.append(node('span', 'metric-category', metric.section), document.createTextNode(metric.metric),
          node('small', '', `${metric.group ? `${metric.group} · ` : ''}${metric.unit}`));
        row.append(label);
        ['current', 'previous', 'wow', 'yearAgo', 'yoy'].forEach(key => {
          const cell = node('td', finite(metric[key]) ? '' : 'unavailable');
          if (key === 'wow' || key === 'yoy') cell.append(changeNode(metric, key));
          else cell.textContent = valueText(metric, metric[key]) + (finite(metric[key]) && metric.unit === '%' ? '%' : '');
          row.append(cell);
        });
        const note = node('td', '', metric.note || (metric.status === 'unavailable' ? '当前值缺失' : '—'));
        note.title = metric.note || '';
        row.append(note);
        body.append(row);
      });
      if (!metrics.length) {
        const row = node('tr', 'empty-row'), cell = node('td', '', '没有匹配的指标，请修改搜索条件。');
        cell.colSpan = 7;
        row.append(cell);
        body.append(row);
      }
      $('#table-count').textContent = `显示 ${metrics.length} / ${data.weeklyMetrics.length} 项指标 · 周报日期 ${data.meta.weeklyDate}`;
    }

    $('#search').addEventListener('input', event => { state.search = event.target.value; renderTable(); });
    $$('.range-buttons button').forEach(button => button.addEventListener('click', () => selectRange(button.dataset.years)));
    $('#date-filter').addEventListener('submit', event => {
      event.preventDefault();
      const start = $('#start-date').value, end = $('#end-date').value;
      if (!start || !end || start > end || !Number.isFinite(timestamp(start)) || !Number.isFinite(timestamp(end))) {
        $('#date-error').textContent = '请选择有效日期，开始日期不能晚于结束日期。';
        $('#date-error').hidden = false;
        return;
      }
      state.start = start;
      state.end = end;
      $('#date-error').hidden = true;
      $$('.range-buttons button').forEach(button => {
        button.classList.remove('selected');
        button.setAttribute('aria-pressed', 'false');
      });
      renderCharts();
    });

    $('#download-csv').addEventListener('click', () => {
      const rows = [['分类', '指标', '单位', '本期', '前期', '环比', '去年同期', '同比', '备注'],
        ...selectedMetrics().map(metric => [metric.section, metric.metric, metric.unit,
          valueText(metric, metric.current), valueText(metric, metric.previous), changeText(metric),
          valueText(metric, metric.yearAgo), changeText(metric, 'yoy'), metric.note])];
      const escape = value => {
        let text = String(value ?? '');
        if (/^[=+@]/.test(text)) text = `'${text}`;
        return `"${text.replaceAll('"', '""')}"`;
      };
      const csv = '\uFEFF' + rows.map(row => row.map(escape).join(',')).join('\r\n');
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
      const link = node('a');
      link.href = url;
      link.download = `煤炭周报指标-${data.meta.weeklyDate}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    $$('.nav-item').forEach(link => link.addEventListener('click', () => {
      $$('.nav-item').forEach(item => item.classList.toggle('active', item === link));
    }));
    selectRange('1');
    renderTable();
  } catch (error) {
    const box = $('#load-error');
    box.hidden = false;
    box.textContent = error.message || '页面未能完成初始化，请刷新重试。';
    console.error(error);
  }
})();

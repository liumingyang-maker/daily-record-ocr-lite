(() => {
  const form = document.getElementById('upload-form');
  const input = document.getElementById('files');
  const preview = document.getElementById('upload-preview');
  const manifest = document.getElementById('rotation-manifest');
  if (!form || !input || !preview || !manifest) return;

  let items = [];

  function syncInput() {
    const transfer = new DataTransfer();
    items.forEach(item => transfer.items.add(item.file));
    input.files = transfer.files;
    manifest.value = JSON.stringify(items.map(item => item.rotation));
  }

  function rotationDegrees(rotation) {
    if (rotation === '90cw') return 90;
    if (rotation === '90ccw') return -90;
    if (rotation === '180') return 180;
    return 0;
  }

  function actionButton(label, action, disabled = false) {
    const element = document.createElement('button');
    element.type = 'button';
    element.className = 'btn btn-small';
    element.textContent = label;
    element.disabled = disabled;
    element.addEventListener('click', action);
    return element;
  }

  function render() {
    preview.replaceChildren();
    items.forEach((item, index) => {
      const card = document.createElement('article');
      card.className = 'upload-card';

      const image = document.createElement('img');
      image.src = item.objectUrl;
      image.alt = `待识别图片 ${index + 1}`;
      image.style.transform = `rotate(${rotationDegrees(item.rotation)}deg)`;

      const name = document.createElement('p');
      name.className = 'img-label';
      name.textContent = `${index + 1}. ${item.file.name}`;

      const actions = document.createElement('div');
      actions.className = 'upload-actions';
      actions.append(
        actionButton('左转', () => { item.rotation = '90ccw'; render(); }),
        actionButton('右转', () => { item.rotation = '90cw'; render(); }),
        actionButton('不旋转', () => { item.rotation = '0'; render(); }),
        actionButton('上移', () => move(index, -1), index === 0),
        actionButton('下移', () => move(index, 1), index === items.length - 1),
        actionButton('删除', () => remove(index)),
      );
      card.append(image, name, actions);
      preview.append(card);
    });
    syncInput();
  }

  function move(index, offset) {
    const target = index + offset;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    render();
  }

  function remove(index) {
    URL.revokeObjectURL(items[index].objectUrl);
    items.splice(index, 1);
    render();
  }

  input.addEventListener('change', () => {
    items.forEach(item => URL.revokeObjectURL(item.objectUrl));
    items = Array.from(input.files || []).map(file => ({
      file,
      rotation: 'auto',
      objectUrl: URL.createObjectURL(file),
    }));
    render();
  });

  form.addEventListener('submit', syncInput);
  window.addEventListener('beforeunload', () => {
    items.forEach(item => URL.revokeObjectURL(item.objectUrl));
  });
})();

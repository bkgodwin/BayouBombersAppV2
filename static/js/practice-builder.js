const dropZone = document.getElementById('practiceDropZone');
const moduleOrderInput = document.getElementById('moduleOrderInput');

if (dropZone && moduleOrderInput) {
  const selectedModules = [];

  function syncModuleOrder() {
    moduleOrderInput.value = JSON.stringify(selectedModules);
  }

  function removeModule(moduleId, node) {
    const idx = selectedModules.indexOf(moduleId);
    if (idx >= 0) selectedModules.splice(idx, 1);
    node.remove();
    syncModuleOrder();
  }

  document.querySelectorAll('#moduleLibrary .module-card .add-btn').forEach((button) => {
    button.addEventListener('click', (event) => {
      const card = event.target.closest('.module-card');
      const moduleId = Number(card?.dataset.moduleId || 0);
      const title = card?.querySelector('h3')?.textContent?.trim() || 'Module';
      const items = Array.from(card?.querySelectorAll('.module-preview li') || []).map((li) => li.textContent.trim());
      if (!moduleId) return;

      selectedModules.push(moduleId);
      syncModuleOrder();

      const added = document.createElement('div');
      added.className = 'added-module';
      const heading = document.createElement('strong');
      heading.textContent = title;
      const list = document.createElement('ul');
      items.forEach((item) => {
        const li = document.createElement('li');
        li.textContent = item;
        list.appendChild(li);
      });
      const removeBtn = document.createElement('button');
      removeBtn.className = 'small-btn';
      removeBtn.type = 'button';
      removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', () => removeModule(moduleId, added));
      added.appendChild(heading);
      added.appendChild(list);
      added.appendChild(removeBtn);
      dropZone.appendChild(added);
    });
  });
}

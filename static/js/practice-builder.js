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
      added.innerHTML = `
        <strong>${title}</strong>
        <ul>${items.map((item) => `<li>${item}</li>`).join('')}</ul>
        <button class="small-btn" type="button">Remove</button>
      `;
      added.querySelector('button').addEventListener('click', () => removeModule(moduleId, added));
      dropZone.appendChild(added);
    });
  });
}

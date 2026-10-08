// Auto-dismiss alerts
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.alert').forEach(a => {
    setTimeout(() => { a.style.opacity='0'; a.style.transition='opacity .5s';
      setTimeout(()=>a.remove(),500); }, 4000);
  });
});

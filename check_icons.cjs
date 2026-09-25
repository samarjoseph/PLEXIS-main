
const fs = require('fs');
function check(file) {
  let content = fs.readFileSync(file, 'utf8');
  let imports = [];
  let m = content.match(/import\s+\{([^}]+)\}\s+from\s+['"]lucide-react['"]/);
  if (m) imports = m[1].split(',').map(s=>s.trim()).filter(Boolean);
  
  let tags = [...content.matchAll(/<([A-Z][a-zA-Z0-9]*)/g)].map(m=>m[1]);
  let uniqueTags = [...new Set(tags)];
  
  // check if any of the commonly used lucide icons are not imported
  // we just list them all
  console.log('--- ' + file + ' ---');
  console.log('Imported:', imports);
  console.log('Tags:', uniqueTags);
}
check('src/components/dashboard/SidebarV2.jsx');
check('src/components/dashboard/ChatAreaV2.jsx');
check('src/components/dashboard/AnalyticsPanelV2.jsx');
check('src/pages/LandingPage.jsx');


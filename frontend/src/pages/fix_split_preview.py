import io

path = "BuilderPortalPage.jsx"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. import line: drop Modal
old1 = "import { Card, Button, Badge, Notice, Spinner, Field, Segmented, Modal, SectionTitle, Toast, Empty } from '../modules/sites/sitesUi'"
new1 = "import { Card, Button, Badge, Notice, Spinner, Field, Segmented, SectionTitle, Toast, Empty } from '../modules/sites/sitesUi'"
assert content.count(old1) == 1, "import: %d" % content.count(old1)
content = content.replace(old1, new1)

# 2. previewOpen state -> mobileTab state
old2 = "  const [undoing, setUndoing] = useState(false)\n  const [previewOpen, setPreviewOpen] = useState(false)"
new2 = ("  const [undoing, setUndoing] = useState(false)\n"
        "  // Mobile-only: which pane is showing (Edit vs Preview) since a phone screen\n"
        "  // has no room for both side by side. Ignored at desktop widths, where the\n"
        "  // CSS below forces both panes visible at once \xe2\x80\x94 see the <style> block in\n"
        "  // the return.\n"
        "  const [mobileTab, setMobileTab] = useState('edit')")
assert content.count(old2) == 1, "state: %d" % content.count(old2)
content = content.replace(old2, new2)

with io.open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("OK - part 1/2 done")

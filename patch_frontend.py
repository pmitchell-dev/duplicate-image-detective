import re

def patch_frontend():
    file_path = r"c:\Users\pmitchell\.gemini\antigravity\scratch\picCurator-Studio-Workspace\web\frontend\src\mobile\MobileCurationView.jsx"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Add state variables
    content = content.replace(
        "const [viewerTags, setViewerTags] = useState([]);",
        "const [viewerTags, setViewerTags] = useState([]);\n  const [viewerDescription, setViewerDescription] = useState(\"\");\n  const [viewerDate, setViewerDate] = useState(\"\");\n  const [metadataModified, setMetadataModified] = useState(false);"
    )

    # 2. Update useEffect for metadata fetching
    old_use_effect = r"// Load tags for the current image\n\s*useEffect\(\(\) => \{\n\s*if \(currentAsset\?\.originalPath\) \{\n\s*setViewerTags\(\[\]\); // clear while loading\n\s*axios\.get\(`\$\{API_BASE\}/tags\?path=\$\{encodeURIComponent\(currentAsset\.originalPath\)\}`\)\n\s*\.then\(res => setViewerTags\(res\.data\.tags \|\| \[\]\)\)\n\s*\.catch\(err => console\.error\(\"Failed to load tags\", err\)\);\n\s*\}\n\s*\}, \[currentAsset\?\.originalPath\]\);"
    
    new_use_effect = """// Load tags and metadata for the current image
  useEffect(() => {
    if (currentAsset?.originalPath) {
      setViewerTags([]); // clear while loading
      setViewerDescription("");
      setViewerDate("");
      setMetadataModified(false);
      axios.get(`${API_BASE}/metadata?path=${encodeURIComponent(currentAsset.originalPath)}`)
        .then(res => {
            setViewerTags(res.data.tags || []);
            setViewerDescription(res.data.description || "");
            setViewerDate(res.data.date || "");
        })
        .catch(err => console.error("Failed to load metadata", err));
    }
  }, [currentAsset?.originalPath]);"""

    content = re.sub(old_use_effect, new_use_effect, content, flags=re.MULTILINE|re.DOTALL)

    # 3. Add handleSaveMetadata
    save_handler = """  const handleSaveMetadata = async () => {
    if (!currentAsset || isProcessing) return;
    setIsProcessing(true);
    try {
      await axios.post(`${API_BASE}/tags`, {
        paths: [currentAsset.originalPath],
        description: viewerDescription,
        date: viewerDate
      });
      setMetadataModified(false);
    } catch (err) {
      console.error(err);
      alert(`Metadata save failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleToggleTag = async (tag) => {"""
    content = content.replace("  const handleToggleTag = async (tag) => {", save_handler)

    # 4. Add Metadata Drawer UI
    old_drawer_end = r"(\s*)\}\)\}\n(\s*)</div>\n(\s*)</div>\n(\s*)\)\)}\n(\s*)</div>\n(\s*)</motion\.div>"
    
    new_metadata_ui = r"""\1})}\n\2</div>\n\3</div>\n\4))}\n
                {/* Metadata Editor Section */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '16px', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '20px' }}>
                  <h4 style={{ margin: 0, color: '#94a3b8', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: 'bold' }}>Metadata</h4>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <label style={{ color: '#cbd5e1', fontSize: '14px' }}>Date</label>
                    <input 
                      type="text" 
                      value={viewerDate}
                      onChange={(e) => { setViewerDate(e.target.value); setMetadataModified(true); }}
                      placeholder="YYYY or YYYY:MM:DD HH:MM:SS"
                      style={{
                        padding: '12px 16px',
                        borderRadius: '12px',
                        backgroundColor: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                        fontSize: '15px',
                        outline: 'none'
                      }}
                    />
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <label style={{ color: '#cbd5e1', fontSize: '14px' }}>Description / Notes</label>
                    <textarea 
                      value={viewerDescription}
                      onChange={(e) => { setViewerDescription(e.target.value); setMetadataModified(true); }}
                      placeholder="Add a description..."
                      rows={3}
                      style={{
                        padding: '12px 16px',
                        borderRadius: '12px',
                        backgroundColor: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'white',
                        fontSize: '15px',
                        outline: 'none',
                        resize: 'vertical'
                      }}
                    />
                  </div>

                  {metadataModified && (
                    <button
                      onClick={handleSaveMetadata}
                      disabled={isProcessing}
                      style={{
                        marginTop: '8px',
                        padding: '12px 16px',
                        borderRadius: '12px',
                        backgroundColor: '#10b981',
                        color: 'white',
                        border: 'none',
                        fontWeight: 'bold',
                        fontSize: '15px',
                        opacity: isProcessing ? 0.7 : 1,
                        cursor: isProcessing ? 'not-allowed' : 'pointer'
                      }}
                    >
                      Save Metadata
                    </button>
                  )}
                </div>\5</div>\6</motion.div>"""
                
    content = re.sub(old_drawer_end, new_metadata_ui, content, flags=re.MULTILINE|re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_frontend()
print("Frontend patched")

using System.Collections.Generic;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Metadata for exported standard view screenshots
    /// </summary>
    public class ViewExportData
    {
        public List<ViewImageInfo> Views { get; set; } = new List<ViewImageInfo>();

        /// <summary>Whether parts were colorized in these views</summary>
        public bool Colorized { get; set; } = false;
    }

    /// <summary>
    /// Info for a single exported view image
    /// </summary>
    public class ViewImageInfo
    {
        /// <summary>Standard view name: "front", "top", "right", "isometric"</summary>
        public string ViewName { get; set; }

        /// <summary>Output filename (e.g., "314884_view_front.png")</summary>
        public string FileName { get; set; }

        /// <summary>Display mode used for the capture</summary>
        public string DisplayMode { get; set; }
    }
}

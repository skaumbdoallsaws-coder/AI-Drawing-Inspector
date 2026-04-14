using System;

namespace SolidWorksExtractor.Models
{
    /// <summary>
    /// Explicit unit representation to prevent scaling errors.
    /// SolidWorks API returns SystemValue in meters - we normalize to all common units.
    /// </summary>
    public class DimensionValue
    {
        /// <summary>Raw value in SI units (meters for length, radians for angles)</summary>
        public double SystemValue { get; set; }

        /// <summary>Value in millimeters</summary>
        public double Millimeters { get; set; }

        /// <summary>Value in inches</summary>
        public double Inches { get; set; }

        /// <summary>Dimension type for context</summary>
        public DimensionType Type { get; set; }

        /// <summary>Human-readable formatted value with units</summary>
        public string Formatted { get; set; }

        public DimensionValue() { }

        /// <summary>
        /// Create from meters (length)
        /// </summary>
        public static DimensionValue FromMeters(double meters)
        {
            return new DimensionValue
            {
                Type = DimensionType.Length,
                SystemValue = meters,
                Millimeters = meters * 1000.0,
                Inches = meters * 39.3701,
                Formatted = $"{meters * 1000:F3}mm ({meters * 39.3701:F4}in)"
            };
        }

        /// <summary>
        /// Create from millimeters (length)
        /// </summary>
        public static DimensionValue FromMillimeters(double mm)
        {
            double meters = mm / 1000.0;
            return new DimensionValue
            {
                Type = DimensionType.Length,
                SystemValue = meters,
                Millimeters = mm,
                Inches = mm / 25.4,
                Formatted = $"{mm:F3}mm ({mm / 25.4:F4}in)"
            };
        }

        /// <summary>
        /// Create from inches (length)
        /// </summary>
        public static DimensionValue FromInches(double inches)
        {
            double meters = inches * 0.0254;
            return new DimensionValue
            {
                Type = DimensionType.Length,
                SystemValue = meters,
                Millimeters = inches * 25.4,
                Inches = inches,
                Formatted = $"{inches * 25.4:F3}mm ({inches:F4}in)"
            };
        }

        /// <summary>
        /// Create from radians (angle)
        /// </summary>
        public static DimensionValue FromRadians(double radians)
        {
            double degrees = radians * (180.0 / Math.PI);
            return new DimensionValue
            {
                Type = DimensionType.Angle,
                SystemValue = radians,
                Millimeters = degrees,  // Repurpose as degrees
                Inches = degrees,       // Same
                Formatted = $"{degrees:F2}°"
            };
        }

        /// <summary>
        /// Create from degrees (angle)
        /// </summary>
        public static DimensionValue FromDegrees(double degrees)
        {
            double radians = degrees * (Math.PI / 180.0);
            return new DimensionValue
            {
                Type = DimensionType.Angle,
                SystemValue = radians,
                Millimeters = degrees,  // Repurpose as degrees
                Inches = degrees,       // Same
                Formatted = $"{degrees:F2}°"
            };
        }

        /// <summary>
        /// Create zero/null dimension
        /// </summary>
        public static DimensionValue Zero(DimensionType type = DimensionType.Length)
        {
            return new DimensionValue
            {
                Type = type,
                SystemValue = 0,
                Millimeters = 0,
                Inches = 0,
                Formatted = type == DimensionType.Angle ? "0°" : "0mm"
            };
        }
    }

    public enum DimensionType
    {
        Length,
        Angle,
        Area,
        Volume,
        Mass
    }

    /// <summary>
    /// 3D point with explicit units
    /// </summary>
    public class Point3D
    {
        public double X { get; set; }  // meters
        public double Y { get; set; }  // meters
        public double Z { get; set; }  // meters

        // Convenience accessors in mm
        public double X_mm => X * 1000;
        public double Y_mm => Y * 1000;
        public double Z_mm => Z * 1000;

        public Point3D() { }

        public Point3D(double x, double y, double z)
        {
            X = x; Y = y; Z = z;
        }

        public static Point3D FromMeters(double x, double y, double z)
        {
            return new Point3D(x, y, z);
        }

        public static Point3D FromArray(double[] arr)
        {
            if (arr == null || arr.Length < 3) return null;
            return new Point3D(arr[0], arr[1], arr[2]);
        }

        public double[] ToArray() => new double[] { X, Y, Z };

        public override string ToString() => $"({X_mm:F3}, {Y_mm:F3}, {Z_mm:F3}) mm";
    }

    /// <summary>
    /// 3D vector (direction, axis)
    /// </summary>
    public class Vector3D
    {
        public double X { get; set; }
        public double Y { get; set; }
        public double Z { get; set; }

        public Vector3D() { }

        public Vector3D(double x, double y, double z)
        {
            X = x; Y = y; Z = z;
        }

        public static Vector3D FromArray(double[] arr)
        {
            if (arr == null || arr.Length < 3) return null;
            return new Vector3D(arr[0], arr[1], arr[2]);
        }

        public double[] ToArray() => new double[] { X, Y, Z };

        /// <summary>
        /// Normalize to unit vector
        /// </summary>
        public Vector3D Normalized()
        {
            double len = Math.Sqrt(X * X + Y * Y + Z * Z);
            if (len < 1e-10) return new Vector3D(0, 0, 1);
            return new Vector3D(X / len, Y / len, Z / len);
        }

        /// <summary>
        /// Check if aligned with axis (within tolerance)
        /// </summary>
        public string GetPrimaryAxis(double tolerance = 0.99)
        {
            var n = Normalized();
            if (Math.Abs(n.Z) > tolerance) return n.Z > 0 ? "+Z" : "-Z";
            if (Math.Abs(n.Y) > tolerance) return n.Y > 0 ? "+Y" : "-Y";
            if (Math.Abs(n.X) > tolerance) return n.X > 0 ? "+X" : "-X";
            return "Angled";
        }

        public override string ToString() => $"<{X:F4}, {Y:F4}, {Z:F4}>";
    }
}

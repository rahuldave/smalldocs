//! Geometry, with a module inside.

/// The distance between two numbers.
pub fn gap(a: f64,  // one number
           b: f64,  // the other
) -> f64 {  // how far apart they are
    (a - b).abs()
}

/// Things on a plane.
pub mod plane {
    /// The area of a rectangle.
    pub fn rect(w: f64,  // the width
                h: f64,  // the height
    ) -> f64 {  // the area
        w * h
    }
}

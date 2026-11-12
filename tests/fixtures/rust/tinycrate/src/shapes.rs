//! Shapes, read from `&[u8]`.

use crate::Shape;

/// A circle.
pub struct Circle {
    /// The radius.
    pub r: f64,
}

impl Shape for Circle {
    fn area(&self) -> f64 {
        3.14159 * self.r * self.r
    }
}

/// Make a unit circle.
pub fn unit() -> Circle {  // a circle of radius 1
    Circle { r: 1.0 }
}

//! A tiny crate for the tests of smalldocs.
//!
//! It has a function, a struct, an enum, a trait and a module.

pub mod shapes;
mod inner;

pub use shapes::Circle;
pub use inner::Token;
pub use inner::helpers::*;
pub use std::collections::HashMap as Map;

/// Add two numbers.
///
/// See [`Point`] and [`std::fmt::Display`].
pub fn add(a: i32,   // the first number
           b: i32,   // the second number
) -> i32 {           // the sum
    a + b
}

/// Scale a number.
///
/// # Arguments
///
/// * `x` - the number
/// * `by` - the factor
pub fn scale(x: f64, by: f64) -> f64 {
    x * by
}

/// Print a greeting.
pub fn greet(mut name: String) {  // the name, which is changed
    name.push('!');
    println!("{name}");
}

pub fn undocumented(x: u8) -> u8 {
    x
}

/// A point in the plane.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    /// Across.
    pub x: f64,
    pub y: f64,  // Up
    hidden: bool,
}

impl Point {
    /// Make a point at the origin.
    pub fn origin() -> Self {  // the point (0, 0)
        Point { x: 0.0, y: 0.0, hidden: false }
    }

    /// The distance to another point.
    pub fn distance(&self,
                    other: &Point,  // the other point
    ) -> f64 {  // the distance
        ((self.x - other.x).powi(2) + (self.y - other.y).powi(2)).sqrt()
    }

    fn secret(&self) -> bool {
        self.hidden
    }
}

impl std::fmt::Display for Point {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "({}, {})", self.x, self.y)
    }
}

/// A colour.
pub enum Colour {
    /// Pure red, not [`Colour::Green`].
    Red,
    Green,  // Pure green
    /// A colour by its parts.
    Rgb(u8, u8, u8),
    /// A named colour.
    Named { name: String },
    /// A mix of three named colours.
    Mix { first: String, second: String, third: String, weight: f64 },
}

/// Something with an area.
pub trait Shape {
    /// The area.
    fn area(&self) -> f64;  // the area, in square units

    /// The name of the shape.
    fn name(&self) -> String {  // the name
        "shape".to_string()
    }
}

/// A number type.
pub type Number = f64;

/// The largest number.
pub const MAX: i32 = 100;

/// Wrap a value.
pub fn wrap<T: Clone>(value: T,  // the value
) -> Option<T>  // the value, wrapped
where
    T: std::fmt::Debug,
{
    Some(value)
}

mod hidden {
    /// A public module inside a private one.
    pub mod deep {
        /// A function deep inside.
        pub fn deepfn() {}
    }

    /// Add, under another name.
    pub fn add_two(a: i32,  // the first
                   b: i32,  // the second
    ) -> i32 {  // the sum
        a + b
    }
}

pub use hidden::deep;
pub use hidden::add_two as plus;

mod cyc_a {
    pub use super::cyc_b::*;
    /// In a.
    pub fn in_a() {}
}

mod cyc_b {
    pub use super::cyc_a::*;
    /// In b.
    pub fn in_b() {}
}

pub use cyc_a::*;

/// A value of either width.
pub struct Holder<T>(pub T);

impl Holder<u8> {
    /// Hold a byte.
    pub fn new(v: u8) -> Self {  // the holder
        Holder(v)
    }
}

impl Holder<u16> {
    /// Hold a word.
    pub fn new(v: u16) -> Self {  // the holder
        Holder(v)
    }
}

/// Apply a function, see [fn@add] and [struct@Point].
pub fn apply<F: Fn(u8) -> u8>(f: F,  // the function
                              x: u8,  // the input
) -> u8
where
    F: Copy,  // a bound
{
    f(x)
}

/// Add a pair.
pub fn pair((b, c): (u8, u8),  // the pair
) -> u8 {  // the sum
    b + c
}

/// Quote a character.
pub fn quote(c: char /* '"' */,  // the character
) -> String {  // the quoted character
    format!("'{c}'")
}

/// A function with a keyword for its name.
pub fn r#type() {}

/// A size.
pub struct Size { pub w: u32, pub h: u32 }  // width and height

/// Show fences.
///
/// ````text
/// ```
/// not closed
/// ````
///
/// # Panics
///
/// Never.
pub fn fences() {}

/// Make a point from its parts.
pub fn point(x: f64,  // across
             y: f64,  // up
) -> Point {  // the point
    Point { x, y, hidden: false }
}

/// A borrowed value.
///
/// # Examples
///
/// ```
/// # use tinycrate::Wrapper;
/// let w = Wrapper { inner: &3 };
/// assert_eq!(*w.get(), 3);
/// ```
pub struct Wrapper<'a, T> {
    pub inner: &'a T,  // The value
}

impl<'a, T: Clone> Wrapper<'a, T> {
    /// The value inside.
    pub fn get(&self) -> &'a T {  // the value
        self.inner
    }
}

/// Make a point from two numbers.
#[macro_export]
macro_rules! point {
    ($x:expr, $y:expr) => {
        $crate::Point { x: $x, y: $y }
    };
}

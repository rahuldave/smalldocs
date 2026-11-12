/** A point on the plane. */
export interface Point {
  x: number;  // the distance across
  y: number;  // the distance up
  label?: string;  // a name to show beside it
}

/** A size, as a width and a height. */
export type Size = {
  width: number;   // across
  height: number;  // up
};

/** A colour by its name. */
export type Colour = "red" | "green" | "blue";

/** The ways a shape can be drawn. */
export enum Style {
  /** Only the outline. */
  Outline = "outline",
  Filled = "filled",  // the inside too
}

/** A rectangle at a point. */
export class Rect {
  /** Where its corner is. */
  corner: Point;
  size: Size;  // how big it is

  /** Make a rectangle. */
  constructor(corner: Point,  // the corner
              size: Size,     // the size
  ) {
    this.corner = corner;
    this.size = size;
  }

  /** The area of the rectangle. */
  area(): number {  // width times height
    return this.size.width * this.size.height;
  }

  /** Move the rectangle. */
  moved(dx: number,  // across
        dy = 0,      // up
  ): Rect {          // a new rectangle
    return new Rect({ x: this.corner.x + dx, y: this.corner.y + dy }, this.size);
  }
}

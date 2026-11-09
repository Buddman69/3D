#!/usr/bin/env python3
"""
Spool ring for Polymaker 3 kg cardboard spools (Fiberon etc.) - by Budd.

Two halves that clamp onto the spool sides and screw together through the
55 mm centre hole. The rims wrap around the cardboard edge so the spool rolls
on the printed rims instead of the cardboard.

No CAD program is used: the solids are built here as exact planar-faced
boundary representations (revolved profiles + a helical thread) and written
straight out as ISO 10303-21 (STEP AP214) text.

    python3 spool_ring.py            # writes the two .step files next to this script

All dimensions in millimetres. Edit PARAMETERS below and re-run.
"""

import math
import os
import sys

# --------------------------------------------------------------------------
# PARAMETERS
# --------------------------------------------------------------------------
# Spool (Polymaker 3 kg cardboard spool, published spec)
SPOOL_OD = 250.0          # +-1
SPOOL_HOLE = 55.0         # +-1
SPOOL_WIDTH = 117.2       # +-2

# Rim / rolling surface
RIM_GAP = 1.0             # min radial gap, spool edge -> inside of rim (at max spool OD)
SPOOL_OD_TOL = 1.0        # spool OD tolerance used for the gap
RIM_WALL = 2.0            # radial thickness of the outer ring
RIM_WIDTH = 12.0          # axial width of the rolling surface (includes side plate)
RIM_CHAMFER = 0.5         # chamfer on the two outer rolling-surface edges
RIM_LEADIN = 0.8          # chamfer on the inside top edge of the rim (guides the spool in)

# Side plate
PLATE = 1.2               # flat side plate thickness
# Lightening windows in the side plate (set WINDOWS = 0 for a solid plate)
WINDOWS = 12              # number of windows / spokes
SPOKE_W = 6.0             # spoke width (parallel sided)
HUB_BAND = 8.0            # solid band around the hub (radial, from hub OD)
RIM_BAND = 7.0            # solid band inside the rim (radial, from rim ID)
WINDOW_FILLET = 4.0       # corner radius of the windows

# Hub (fits in the 55 mm hole)
HUB_OD = 54.6             # snug in the 55 mm hole - adjust after a test print
HUB_CHAMFER = 1.0         # lead-in chamfer on the hub ends

# Thread (coarse, FDM friendly, right hand)
PITCH = 4.0
THREAD_H = 2.0            # radial thread depth
THREAD_ROOT = 1.0         # axial width of the flat root
THREAD_CREST = 0.7        # axial width of the flat crest
THREAD_GAP = 0.3          # radial clearance between male and female
FEMALE_MAJOR_D = 48.0     # bore of the female hub (thread root)
MALE_BORE = 38.0          # through-hole in the male half
RAMP_TURNS = 0.5          # thread run-in / run-out length in turns

# Lengths (measured from the inside face of each side plate)
FEMALE_HUB_LEN = 80.0     # Half A sleeve length
FEMALE_THREAD_TURNS = 9   # threaded length = turns * pitch, at the open end
MALE_COLLAR_LEN = 15.0    # Half B snug collar
MALE_HUB_LEN = 60.0       # Half B threaded tube length
MALE_THREAD_TURNS = 10
END_MARGIN = 0.6          # plain band left at the end of each threaded tube

# Facet resolution (segments per revolution)
N_RIM = 360               # rim: 0.005 mm chord error
N_HUB = 120               # hub / thread: <0.01 mm chord error

# --------------------------------------------------------------------------
# derived
# --------------------------------------------------------------------------
R_RIM_IN = (SPOOL_OD + SPOOL_OD_TOL) / 2 + RIM_GAP
R_RIM_OUT = R_RIM_IN + RIM_WALL
R_HUB = HUB_OD / 2
R_F0 = FEMALE_MAJOR_D / 2                 # female root radius
R_M0 = R_F0 - THREAD_H - THREAD_GAP       # male root radius
R_MBORE = MALE_BORE / 2
FLANK = (PITCH - THREAD_ROOT - THREAD_CREST) / 2
V_BREAKS = (0.0, THREAD_ROOT, THREAD_ROOT + FLANK, THREAD_ROOT + FLANK + THREAD_CREST)


# --------------------------------------------------------------------------
# B-rep mesh: vertices + planar faces (each face = list of loops of vertex ids,
# first loop outer, CCW about the outward normal)
# --------------------------------------------------------------------------
class Solid:
    def __init__(self, name):
        self.name = name
        self.v = []
        self.faces = []

    def vert(self, r, theta, z):
        self.v.append((r * math.cos(theta), r * math.sin(theta), z))
        return len(self.v) - 1

    def ring(self, r, z, n, phase=0.0):
        return [self.vert(r, phase + 2 * math.pi * j / n, z) for j in range(n)]

    def face(self, *loops):
        self.faces.append([list(l) for l in loops])


def band(s, P, Q):
    """Surface swept by profile segment P->Q (rings of equal size)."""
    n = len(P)
    assert len(Q) == n
    for j in range(n):
        k = (j + 1) % n
        s.face([P[j], P[k], Q[k], Q[j]])


def annulus(s, ring_out, ring_in, normal_up, holes=()):
    """Flat ring face. `holes` are extra CCW (seen from +z) polygons cut through it."""
    if normal_up:
        s.face(ring_out, list(reversed(ring_in)), *[list(reversed(h)) for h in holes])
    else:
        s.face(list(reversed(ring_out)), ring_in, *holes)


def window_outline():
    """CCW (seen from +z) outline of one plate window centred on angle 0 as (x, y) points:
    an annular sector between two parallel-sided spokes with filleted corners."""
    rf = WINDOW_FILLET
    r_in = R_HUB + HUB_BAND
    r_out = R_RIM_IN - RIM_BAND
    half = math.pi / WINDOWS
    s1, s2 = -half, half                      # spoke centre lines either side
    d = SPOKE_W / 2 + rf                      # inner (shrunk) shape offsets

    def on_line(phi, side, r):
        # point on the line parallel to spoke `phi` at distance d (side=+1 -> +theta side), radius r
        t = (-math.sin(phi) * side, math.cos(phi) * side)
        along = math.sqrt(r * r - d * d)
        return (along * math.cos(phi) + d * t[0], along * math.sin(phi) + d * t[1])

    qo1, qo2 = on_line(s1, +1, r_out - rf), on_line(s2, -1, r_out - rf)
    qi2, qi1 = on_line(s2, -1, r_in + rf), on_line(s1, +1, r_in + rf)
    pts = []

    def arc(cx, cy, r, a0, a1, n):
        for k in range(n):
            a = a0 + (a1 - a0) * k / n
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    ang = lambda q: math.atan2(q[1], q[0])
    n_out = max(8, int(abs(ang(qo2) - ang(qo1)) * r_out / 1.5))
    n_in = max(4, int(abs(ang(qi2) - ang(qi1)) * r_in / 1.0))
    t2 = s2 + math.pi / 2                     # normal of side 2, pointing into spoke 2
    t1 = s1 - math.pi / 2                     # normal of side 1, pointing into spoke 1
    arc(0, 0, r_out, ang(qo1), ang(qo2), n_out)                       # outer edge
    arc(*qo2, rf, ang(qo2), t2, 8)                                    # corner
    pts.append((qo2[0] + rf * math.cos(t2), qo2[1] + rf * math.sin(t2)))  # side 2 runs inward
    arc(*qi2, rf, t2, ang(qi2) + math.pi, 8)                          # corner
    arc(0, 0, r_in, ang(qi2), ang(qi1), n_in)                         # inner edge (clockwise)
    arc(*qi1, rf, ang(qi1) + math.pi, t1 + 2 * math.pi, 8)            # corner
    pts.append((qi1[0] + rf * math.cos(t1), qi1[1] + rf * math.sin(t1)))  # side 1 runs outward
    arc(*qo1, rf, t1, ang(qo1), 8)                                    # corner
    return pts


def plate_windows(s):
    """Build the window walls. Returns (holes at z=0, holes at z=PLATE)."""
    if not WINDOWS:
        return [], []
    base = window_outline()
    lo_all, hi_all = [], []
    for w in range(WINDOWS):
        a = 2 * math.pi * (w + 0.5) / WINDOWS        # a spoke on +X (and every 360/WINDOWS deg)
        c, si = math.cos(a), math.sin(a)
        lo, hi = [], []
        for x, y in base:
            X, Y = c * x - si * y, si * x + c * y
            s.v.append((X, Y, 0.0)); lo.append(len(s.v) - 1)
            s.v.append((X, Y, PLATE)); hi.append(len(s.v) - 1)
        n = len(lo)
        for j in range(n):                           # wall, normal into the window
            k = (j + 1) % n
            s.face([lo[j], hi[j], hi[k], lo[k]])
        lo_all.append(lo); hi_all.append(hi)
    return lo_all, hi_all


def threaded_wall(s, r0, z0, z1, n, turns, z_start, sign, outward):
    """
    Cylinder wall r=r0 from z0 to z1 carrying a helical thread ribbon.
    sign=+1: ridge grows outward (male), -1: inward (female).
    outward=True when the wall's outward normal is +r (male outer wall).
    Returns (bottom ring, top ring) at z0 / z1.
    """
    M = turns * n
    zt = z_start + PITCH * (turns + 1)
    assert z0 < z_start - 1e-6 and zt < z1 - 1e-6, "thread does not fit wall"
    faces = []

    def ramp(i):
        return max(0.0, min(1.0, min(i, M - i) / (n * RAMP_TURNS)))

    def ang(i):
        return 2 * math.pi * i / n

    def zh(i, k):
        return z_start + PITCH * i / n + V_BREAKS[k]

    # helix lines: line 0 (root start) runs i=0..M+n, lines 1..3 run i=0..M
    L = {}
    for i in range(M + n + 1):
        L[(i, 0)] = s.vert(r0, ang(i), zh(i, 0))
    for i in range(M + 1):
        h = sign * THREAD_H * ramp(i)
        L[(i, 1)] = s.vert(r0, ang(i), zh(i, 1))
        L[(i, 2)] = s.vert(r0 + h, ang(i), zh(i, 2))
        L[(i, 3)] = s.vert(r0 + h, ang(i), zh(i, 3))

    def pt(i, k):
        return L[(i + n, 0)] if k == 4 else L[(i, k)]

    for i in range(M):
        for k in range(4):
            a, b, c, d = pt(i, k), pt(i + 1, k), pt(i + 1, k + 1), pt(i, k + 1)
            if k in (0, 2):                       # root / crest: planar quad
                faces.append([a, b, c, d])
            else:                                 # flanks: two triangles
                faces.append([a, b, c])
                faces.append([a, c, d])

    B = s.ring(r0, z0, n)
    T = [s.vert(r0, ang(M + j), z1) for j in range(n)]
    # bottom strip under the first turn
    for j in range(n - 1):
        faces.append([B[j], B[j + 1], L[(j + 1, 0)], L[(j, 0)]])
    faces.append([B[n - 1], B[0], L[(0, 0)], L[(0, 1)], L[(0, 2)], L[(0, 3)],
                  L[(n, 0)], L[(n - 1, 0)]])
    # top strip over the last turn
    faces.append([L[(M, 0)], L[(M + 1, 0)], T[1], T[0], L[(M + n, 0)],
                  L[(M, 3)], L[(M, 2)], L[(M, 1)]])
    for j in range(1, n):
        a, b = L[(M + j, 0)], L[(M + j + 1, 0)]
        faces.append([a, b, T[(j + 1) % n], T[j]])

    for f in faces:
        s.face(f if outward else list(reversed(f)))
    return B, T


def rim_and_plate(s):
    """Rim + chamfers. Returns (outer ring of the bed face, rim-inner ring at plate top)."""
    c = RIM_CHAMFER
    r0 = s.ring(R_RIM_OUT - c, 0.0, N_RIM)
    r1 = s.ring(R_RIM_OUT, c, N_RIM)
    r2 = s.ring(R_RIM_OUT, RIM_WIDTH - c, N_RIM)
    r3 = s.ring(R_RIM_OUT - c, RIM_WIDTH, N_RIM)
    r4 = s.ring(R_RIM_IN + RIM_LEADIN, RIM_WIDTH, N_RIM)
    r4b = s.ring(R_RIM_IN, RIM_WIDTH - RIM_LEADIN, N_RIM)
    r5 = s.ring(R_RIM_IN, PLATE, N_RIM)
    band(s, r0, r1)
    band(s, r1, r2)
    band(s, r2, r3)
    annulus(s, r3, r4, normal_up=True)           # rim top edge
    band(s, r4, r4b)                             # lead-in chamfer
    band(s, r4b, r5)                             # rim inner wall
    return r0, r5


def half_a():
    """Female half: plate + rim + long snug sleeve with internal thread at its open end."""
    s = Solid("Spool Ring Half A (female)")
    bottom_out, plate_out = rim_and_plate(s)
    z_top = PLATE + FEMALE_HUB_LEN
    ch = HUB_CHAMFER
    h0 = s.ring(R_HUB, PLATE, N_HUB)
    h1 = s.ring(R_HUB, z_top - ch, N_HUB)
    h2 = s.ring(R_HUB - ch, z_top, N_HUB)
    w_lo, w_hi = plate_windows(s)
    annulus(s, plate_out, h0, normal_up=True, holes=w_hi)    # plate inner face
    band(s, h0, h1)
    band(s, h1, h2)
    z_start = z_top - END_MARGIN - PITCH * FEMALE_THREAD_TURNS
    B, T = threaded_wall(s, R_F0, 0.0, z_top, N_HUB, FEMALE_THREAD_TURNS - 1,
                         z_start, sign=-1, outward=False)
    annulus(s, h2, T, normal_up=True)            # sleeve end
    annulus(s, bottom_out, B, normal_up=False, holes=w_lo)   # print-bed face
    return s


def half_b():
    """Male half: plate + rim + snug collar + externally threaded tube."""
    s = Solid("Spool Ring Half B (male)")
    bottom_out, plate_out = rim_and_plate(s)
    ch = HUB_CHAMFER
    z_c = PLATE + MALE_COLLAR_LEN
    z_top = PLATE + MALE_HUB_LEN
    c0 = s.ring(R_HUB, PLATE, N_HUB)
    c1 = s.ring(R_HUB, z_c - ch, N_HUB)
    c2 = s.ring(R_HUB - ch, z_c, N_HUB)
    w_lo, w_hi = plate_windows(s)
    annulus(s, plate_out, c0, normal_up=True, holes=w_hi)
    band(s, c0, c1)
    band(s, c1, c2)
    z_start = z_top - END_MARGIN - PITCH * MALE_THREAD_TURNS
    B, T = threaded_wall(s, R_M0, z_c, z_top, N_HUB, MALE_THREAD_TURNS - 1,
                         z_start, sign=+1, outward=True)
    annulus(s, c2, B, normal_up=True)            # collar shoulder
    i_top = [s.vert(R_MBORE, 2 * math.pi * j / N_HUB, z_top) for j in range(N_HUB)]
    i_bot = s.ring(R_MBORE, 0.0, N_HUB)
    annulus(s, T, i_top, normal_up=True)         # tube end
    band(s, i_top, i_bot)                        # through bore
    annulus(s, bottom_out, i_bot, normal_up=False, holes=w_lo)
    return s


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def newell(pts):
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        x1, y1, z1 = pts[i]
        x2, y2, z2 = pts[(i + 1) % len(pts)]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return nx, ny, nz


def check(s):
    from collections import Counter
    directed = Counter()
    n_loops = 0
    worst_planar = 0.0
    vol = 0.0
    for f in s.faces:
        allpts = []
        for loop in f:
            n_loops += 1
            for i in range(len(loop)):
                directed[(loop[i], loop[(i + 1) % len(loop)])] += 1
            allpts += [s.v[i] for i in loop]
        nx, ny, nz = newell([s.v[i] for i in f[0]])
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        assert ln > 1e-12, "degenerate face"
        n = (nx / ln, ny / ln, nz / ln)
        p0 = s.v[f[0][0]]
        for p in allpts:
            d = abs(sum((p[k] - p0[k]) * n[k] for k in range(3)))
            worst_planar = max(worst_planar, d)
        for loop in f:                            # divergence theorem volume
            a = s.v[loop[0]]
            for i in range(1, len(loop) - 1):
                b, c = s.v[loop[i]], s.v[loop[i + 1]]
                vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                        - a[1] * (b[0] * c[2] - b[2] * c[0])
                        + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    bad = [e for e, c in directed.items() if c != 1 or directed.get((e[1], e[0]), 0) != 1]
    used = {v for e in directed for v in e}
    V, E, F = len(used), len(directed) // 2, len(s.faces)
    holes = n_loops - F
    euler = V - E + F - holes
    print(f"  {s.name}: V={V} E={E} F={F} inner-loops={holes} "
          f"Euler={euler} (expect {-2 * WINDOWS}), non-manifold edges={len(bad)}, "
          f"max planarity dev={worst_planar:.2e} mm, volume={vol / 1000:.1f} cm^3")
    assert not bad and euler == -2 * WINDOWS and vol > 0 and worst_planar < 1e-6
    return vol


# --------------------------------------------------------------------------
# STEP writer (AP214, advanced B-rep with planar faces)
# --------------------------------------------------------------------------
def write_step(s, path):
    out = []
    eid = [0]

    def ent(text):
        eid[0] += 1
        out.append(f"#{eid[0]}={text};")
        return eid[0]

    def f(x):
        t = f"{x:.6f}".rstrip("0")
        return t + "0" if t.endswith(".") else t

    def unit(vec):
        l = math.sqrt(sum(c * c for c in vec))
        return tuple(c / l for c in vec)

    def direction(d):
        return ent(f"DIRECTION('',({f(d[0])},{f(d[1])},{f(d[2])}))")

    def point(p):
        return ent(f"CARTESIAN_POINT('',({f(p[0])},{f(p[1])},{f(p[2])}))")

    # header / product structure
    app = ent("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    ent(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})")
    pc = ent(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    prod = ent(f"PRODUCT('{s.name}','{s.name}','',(#{pc}))")
    ent(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#{prod}))")
    pdf = ent(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pdc = ent(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    pd = ent(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdc})")
    pds = ent(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    mm = ent("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    rad = ent("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    sr = ent("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    unc = ent(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),#{mm},"
              f"'distance_accuracy_value','confusion accuracy')")
    ctx = ent(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc}))"
              f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{mm},#{rad},#{sr}))REPRESENTATION_CONTEXT('',''))")

    # vertices
    used = sorted({i for fc in s.faces for loop in fc for i in loop})
    vp = {}
    for i in used:
        vp[i] = ent(f"VERTEX_POINT('',#{point(s.v[i])})")

    # edges
    edges = {}

    def edge(a, b):
        key = (min(a, b), max(a, b))
        if key not in edges:
            pa, pb = s.v[key[0]], s.v[key[1]]
            d = [pb[k] - pa[k] for k in range(3)]
            ln = math.sqrt(sum(c * c for c in d))
            line = ent(f"LINE('',#{point(pa)},#{ent(f'VECTOR({chr(39)}{chr(39)},#{direction(unit(d))},{f(ln)})')})")
            edges[key] = ent(f"EDGE_CURVE('',#{vp[key[0]]},#{vp[key[1]]},#{line},.T.)")
        return edges[key], a == min(a, b)

    face_ids = []
    for fc in s.faces:
        n = unit(newell([s.v[i] for i in fc[0]]))
        p0 = s.v[fc[0][0]]
        p1 = s.v[fc[0][1]]
        xd = [p1[k] - p0[k] for k in range(3)]
        dot = sum(xd[k] * n[k] for k in range(3))
        xd = unit([xd[k] - dot * n[k] for k in range(3)])
        ax = ent(f"AXIS2_PLACEMENT_3D('',#{point(p0)},#{direction(n)},#{direction(xd)})")
        plane = ent(f"PLANE('',#{ax})")
        bounds = []
        for li, loop in enumerate(fc):
            oes = []
            for i in range(len(loop)):
                e, same = edge(loop[i], loop[(i + 1) % len(loop)])
                oes.append(ent(f"ORIENTED_EDGE('',*,*,#{e},{'.T.' if same else '.F.'})"))
            el = ent("EDGE_LOOP('',(" + ",".join(f"#{o}" for o in oes) + "))")
            kind = "FACE_OUTER_BOUND" if li == 0 else "FACE_BOUND"
            bounds.append(ent(f"{kind}('',#{el},.T.)"))
        face_ids.append(ent("ADVANCED_FACE('',(" + ",".join(f"#{b}" for b in bounds)
                            + f"),#{plane},.T.)"))

    shell = ent("CLOSED_SHELL('',(" + ",".join(f"#{x}" for x in face_ids) + "))")
    brep = ent(f"MANIFOLD_SOLID_BREP('{s.name}',#{shell})")
    origin = ent(f"AXIS2_PLACEMENT_3D('',#{point((0, 0, 0))},#{direction((0, 0, 1))},"
                 f"#{direction((1, 0, 0))})")
    rep = ent(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#{brep},#{origin}),#{ctx})")
    ent(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")

    fname = os.path.basename(path)
    header = [
        "ISO-10303-21;",
        "HEADER;",
        f"FILE_DESCRIPTION(('{s.name} - Polymaker 3kg spool ring by Budd'),'2;1');",
        f"FILE_NAME('{fname}','2026-11-09T00:00:00',('Budd'),(''),"
        "'spool_ring.py','spool_ring.py (no CAD)','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
        "ENDSEC;",
        "DATA;",
    ]
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(header + out + ["ENDSEC;", "END-ISO-10303-21;", ""]))
    print(f"  wrote {fname}  ({os.path.getsize(path) / 1e6:.1f} MB, {len(s.faces)} faces)")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    print(f"Rim ID {2 * R_RIM_IN:.1f} / OD {2 * R_RIM_OUT:.1f} mm, hub OD {HUB_OD} mm")
    print(f"Thread: female root D{2 * R_F0:.1f} crest D{2 * (R_F0 - THREAD_H):.1f} | "
          f"male root D{2 * R_M0:.1f} crest D{2 * (R_M0 + THREAD_H):.1f} | pitch {PITCH}")
    for build, fname in ((half_a, "Spool Ring Half A (female).step"),
                         (half_b, "Spool Ring Half B (male).step")):
        s = build()
        check(s)
        write_step(s, os.path.join(here, fname))


if __name__ == "__main__":
    sys.exit(main())

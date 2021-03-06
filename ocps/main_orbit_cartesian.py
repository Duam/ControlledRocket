#!/usr/bin/python3

##
# @file main_orbit_cartesian.py
# @author Paul Daum
# @brief Optimize spacecraft trajectory to reach a circular orbit at 
#        a specified altitude. Uses multiple shooting. Currently unused.
##

import sys, os
sys.path.append(os.path.realpath('../'))
sys.path.append(os.getcwd())

import casadi as cas
import numpy as np
from models.orbit_cartesian_model.orbit_cartesian_model import orbit_cartesian_model
from integrators.rk4step import rk4step_L, rk4step_ode

# Create a spacecraft instance
spacecraft = orbit_cartesian_model()

# Print parameters
print("== Universe parameters ==")
print("Grav. const. G: " + str(spacecraft.G) + " m^3/(kg*s^2)")
print("Moon mass M: " + str(spacecraft.M) + " kg")
print("Moon radius R: " + str(spacecraft.R) + " m")

print("== Spacecraft parameters ==")
print("Initial mass: " + str(spacecraft.m0) + " kg")
print("Empty mass: " + str(spacecraft.me) + " kg")
print("Max. thrust: " + str(spacecraft.u_max) + " N")
print("Fuel consumption coeff:" + str(spacecraft.km) + " kg/s")
print("Initial state: " + str(spacecraft.x0))
print("Initial state (scaled): " + str(spacecraft.x0_scaled))
print("State scale vector: " + str(spacecraft.scale))
print("State unscale vector: " + str(spacecraft.unscale))
print("Number of states: " + str(spacecraft.nx))
print("Number of controls: " + str(spacecraft.nu))

# Simulation parameters
T = 600.0
N = 100
DT = T/N

# Integration parameters
nn = 10
h = DT/nn

# Values for terminal constraints
altitude_T = 20000 # [m]
angVel_T = np.sqrt(spacecraft.mu / (spacecraft.R + altitude_T)**3) # [rad]

# Print out values
print("== Terminal values ==")
print("Altitude: " + str(altitude_T) + " m")
print("Angular velocity: " + str(angVel_T) + " rad")

# Create system model in casadi
x = cas.MX.sym('x', spacecraft.nx, 1)
u = cas.MX.sym('u', spacecraft.nu, 1)
f = cas.Function('f', [x,u], [spacecraft.dynamics_scaled(x,u)], ['x','u'], ['xdot'])

# Create an integrator for the ode
Xk = x
for k in range(nn):
    Xk = rk4step_ode(f, Xk, u, h)
F = cas.Function('F', [x,u], [Xk], ['x','u'], ['xk'])

# Create stage cost for the OCP
l = u[0]**2 + u[1]**2
l = cas.Function('l', [x,u], [l], ['x','u'], ['l'])

# Create an integrator for the stage cost
Lk = 0
for k in range(nn):
    Lk = rk4step_L(l, Lk, x, u, h)
L = cas.Function('L', [x,u], [Lk], ['x','u'], ['L'])

# Create an initial guess for the OCP by forward simulation
us_init = np.zeros((N,spacecraft.nu))
n_x_stop = 50
n_y_stop = 50

us_init[0:n_x_stop,0] = 0.11 * np.ones(n_x_stop)
us_init[0:n_y_stop,1] = 0.5 * np.ones(n_y_stop)

xs = cas.DM.zeros((N+1, spacecraft.nx))
xs[0,:] = spacecraft.x0_scaled
for k in range(N):
    xs[k+1,:] = F(xs[k,:],us_init[k,:])

xs_init = xs.full()

# Print debug message
print("== Initial guess ==")
print("xs_init size: " + str(xs_init.shape))
print("us_init size: " + str(us_init.shape))
print(xs_init)
print("Initial guess computed. Now starting creation of OCP.")

# Create the optimization variables
X = cas.MX.sym('X', spacecraft.nx, N)
U = cas.MX.sym('U', spacecraft.nu, N)

# Start with empty NLP
w = []      # Optimization variables (xs, us)
w0 = []     # Initial guess
lbw = []    # Lower bound on opt. variables
ubw = []    # Upper bound on opt. variables
J = 0       # Cost function
g = []      # Nonlinear constraints
lbg = []    # Lower bound on constraints
ubg = []    # Upper bound on constraints

# Formulate NLP
Xk = xs_init[0,:]
for k in range(N):
    
    # NLP variable for control
    Uk = cas.MX.sym('U_' + str(k), spacecraft.nu, 1)
    w = cas.vertcat(w, Uk)
    lbw = cas.vertcat(lbw, -cas.inf, -cas.inf)
    ubw = cas.vertcat(ubw,  cas.inf,  cas.inf)
    w0 = cas.vertcat(w0, us_init[k,:])

    # Circle constraints on controls
    g = cas.vertcat(g, Uk[0]**2 + Uk[1]**2)
    lbg = cas.vertcat(lbg, 0)
    ubg = cas.vertcat(ubg, 1)

    # Integrate till the end of the interval
    Xk_end = F(Xk, Uk)
    J = J + L(Xk, Uk)

    # New NLP variable for state
    Xk = cas.MX.sym('X_' + str(k+1), spacecraft.nx, 1)
    w = cas.vertcat(w, Xk)
    lbw_k = cas.vertcat(
        -cas.inf,
        -cas.inf,
        -cas.inf,
        -cas.inf,
        spacecraft.me * spacecraft.scale[4]
    )
    ubw_k = cas.vertcat(
        cas.inf,
        cas.inf,
        cas.inf,
        cas.inf,
        spacecraft.m0 * spacecraft.scale[4]
    )
    lbw = cas.vertcat(lbw, lbw_k)
    ubw = cas.vertcat(ubw, ubw_k)
    w0 = cas.vertcat(w0, xs_init[k+1,:])

    # Circle constraint on position
    g = cas.vertcat(g, Xk_end[0]**2 + Xk_end[1]**2)
    lbg = cas.vertcat(lbg, (spacecraft.R * spacecraft.scale[0])**2)
    ubg = cas.vertcat(ubg, cas.inf)

    # Equality constraints to match intervals
    g = cas.vertcat(g, Xk_end - Xk)
    lbg = cas.vertcat(lbg, cas.DM.zeros(spacecraft.nx, 1))
    ubg = cas.vertcat(ubg, cas.DM.zeros(spacecraft.nx, 1))


# Terminal constraint on altitude
dist2_T = ((spacecraft.R + altitude_T) * spacecraft.scale[0])**2
g = cas.vertcat(g, Xk_end[0]**2 + Xk_end[1]**2)
lbg = cas.vertcat(lbg, dist2_T)
ubg = cas.vertcat(ubg, dist2_T)

# Terminal constraint on radial velocity
p = Xk_end[0:2]
v = Xk_end[2:4]
v_rad = cas.dot(p, v)
'''g = cas.vertcat(g, v_rad)
lbg = cas.vertcat(lbg, 0)
ubg = cas.vertcat(ubg, 0)
'''
# Terminal constraint on angular velocity
v_T = dist2_T * angVel_T**2
'''g = cas.vertcat(g, v[0]**2 + v[1]**2)
lbg = cas.vertcat(lbg, v_T)
ubg = cas.vertcat(ubg, v_T)
'''

print("== Terminal constraints ==")
print("Distance from origin: " + str(np.sqrt(dist2_T)) + " km")
print("Radial velocity: 0 km/s")
print("Velocity norm: " + str(np.sqrt(v_T)) + " km/s")

# Print debug message
print("== OCP created ==")
print("w size: " + str(w.shape) + ", type: " + str(type(w)))
print("w0 size: " + str(w0.shape)  + ", type: " + str(type(w0)))
print("lbw size: " + str(lbw.shape) + ", type: " + str(type(lbw)))
print("ubw size: " + str(ubw.shape) + ", type: " + str(type(ubw)))
print("J size: " + str(J.shape) + ", type: " + str(type(J)))
print("g size: " + str(g.shape) + ", type: " + str(type(g)))
print("lbg size: " + str(lbg.shape)  + ", type: " + str(type(lbg)))
print("ubg size: " + str(ubg.shape) + ", type: " + str(type(ubg)))
print("Setting up and starting solver")

# Create an NLP solver
nlp = {}
nlp['f'] = J
nlp['x'] = w
nlp['g'] = g

opts = {}
#opts['ipopt.print_level'] = 0
opts['ipopt.print_info_string'] = 'yes'
solver = cas.nlpsol('solver', 'ipopt', nlp, opts)

# Solve the NLP
solver_in = {}
solver_in['x0'] = w0
solver_in['lbx'] = lbw
solver_in['ubx'] = ubw
solver_in['lbg'] = lbg
solver_in['ubg'] = ubg
solver_out = solver(**solver_in)
print("== OCP solved ==")

# Extract results
sol = solver_out['x']
print("sol size: " + str(sol.shape) + ", type: " + str(type(sol)))

u_opt = cas.DM.zeros((N,spacecraft.nu))
x_opt = cas.DM.zeros((N,spacecraft.nx))

nxnu = spacecraft.nx + spacecraft.nu

u_opt[:,0] = sol[0::nxnu]
u_opt[:,1] = sol[1::nxnu]
x_opt[:,0] = sol[2::nxnu]
x_opt[:,1] = sol[3::nxnu]
x_opt[:,2] = sol[4::nxnu]
x_opt[:,3] = sol[5::nxnu]
x_opt[:,4] = sol[6::nxnu]

# Write to .xml file
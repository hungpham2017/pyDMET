'''
Testing the implementation of the Schmidt decomposition class.
'''

import pyscf
from pyscf import gto, scf, ao2mo
import numpy as np
import pytest
from mdmet import orthobasis, schmidtbasis, qcsolvers
from functools import reduce

numBathOrbs = 2

def test_makemole():
	bondlength = 1.0
	nat = 10
	mol = gto.Mole()
	mol.atom = []
	r = 0.5 * bondlength / np.sin(np.pi/nat)
	for i in range(nat):
		theta = i * (2*np.pi/nat)
		mol.atom.append(('H', (r*np.cos(theta), r*np.sin(theta), 0)))

	mol.basis = 'sto-3g'
	mol.build(verbose=0)

	mf = scf.RHF(mol)
	mf.scf()
	impOrbs = np.zeros(mol.nao_nr())
	impOrbs[-numBathOrbs:] = 1

	return mol, mf, impOrbs 
	
def test_makemole2():
	bondlength = 1.0
	mol = gto.M(atom='He 0 0.5 0; He -0.5 0 0; Be 1 0 0; Be 2 0 0; He 3 0.5 0; He 3 -0.5 0', basis='sto-6g')
	mol.build(verbose=0)
	mf = scf.RHF(mol)
	mf.scf()
	
	unit_sizes = np.array([ 2, 5, 5, 2])
	impClusters = []
	for frag in range(4):
		impurity_orbitals = np.zeros( [mol.nao_nr()], dtype = int)
		start = unit_sizes[:frag].sum()
		impurity_orbitals[start:(start + unit_sizes[frag])] = 1
		impClusters.append(impurity_orbitals)	
	return mol, mf, impClusters 	

# The energies calculated in two different basis have to be the same
def test_Etotal_newspace():
	mol, mf, impOrbs  = test_makemole()
	nocc = mol.nelectron // 2
	S = mf.get_ovlp() 
		
	umat = np.zeros((mol.nao_nr(), mol.nao_nr()))
	ortho = orthobasis.Orthobasis(mf, method = 'overlap')
	orthoOED = ortho.construct_orthoOED(umat, OEH_type = 'FOCK')
	schmidt = schmidtbasis.RHF_decomposition(mf, impOrbs, numBathOrbs, orthoOED)	
	schmidt.method = 'overlap'
	BathOrbs, FBEorbs, envOrbs = schmidt.baths()

	OEIortho = ortho.orthoOEI
	TEIortho = ortho.orthoTEI
	Norb = ortho.Norbs
	
	numAct = 2*BathOrbs

	Norb2 = FBEorbs.shape[1]
	OEIdmet = reduce(np.dot,(FBEorbs.T, OEIortho, FBEorbs))
	TEIdmet = ao2mo.incore.full(ao2mo.restore(8, TEIortho, Norb), FBEorbs, compact=False).reshape(Norb2, Norb2, Norb2, Norb2)	

	Ddmet = reduce(np.dot, (FBEorbs.T, orthoOED[1], FBEorbs))
	
	Edmet = np.einsum('pq,pq',OEIdmet,Ddmet) + 0.5*np.einsum('pq,rs,pqrs',Ddmet,Ddmet,TEIdmet) - 0.25*np.einsum('ps,rq,pqrs',Ddmet,Ddmet,TEIdmet) + mol.energy_nuc()
	

	assert np.isclose(Edmet, mf.e_tot)

'''
This test is performed to check the exactness of embedding scheme in two different bath construction methods
In general, the full system energy = E_fragment + E_bath + E_unentangled_environment

$THEN:
HOWEVER:
- When using 1-rdm as the projector, one can partition the total energy into the energies for each fragment.
That means: E_total = Sigma (E_x). This is called a "democratic partition" of unlocal operators.
This is correct since the Hilbert space is partitioned into the fragments space (not including the bath or 
unentangled environment orbitals). The embedding system has 2 x (the number of electrons in the fragment) electrons

- When using the overlap matrix between occ orbitals and local basis functions, one CANNOT do the above partition.
This partition of Hilbert space projects the hole states into the local functions space (fragment) and its complementary 
space (bath). The embedding system has 2 x (the number of orbitals in the fragment) electrons.
Adding up all fragment electrons does not result in the total electrons of the total system.
How people calculate the fragment energy in this case?
$NOW:
SOLVED (overcomplicate the projectors when working in a orthogonal basis).
Two scheme give exactly the same embedding basis
'''	
def test_bathconstruction():
	mol, mf, impOrbs  = test_makemole()
	nocc = mol.nelectron // 2
	
	umat = np.zeros((mol.nao_nr(), mol.nao_nr()))
	ortho = orthobasis.Orthobasis(mf, method = 'overlap')
	orthoOED = ortho.construct_orthoOED(umat, OEH_type = 'FOCK')
	schmidt = schmidtbasis.RHF_decomposition(mf, impOrbs, numBathOrbs, orthoOED)	

	schmidt.method = 'overlap'
	BathOrbs1, FBEorbs1, envOrbs = schmidt.baths()
	
	schmidt.method = 'OED'	
	BathOrbs2, FBEorbs2, core_eigenvals = schmidt.baths()
	
	OEIortho = ortho.orthoOEI
	TEIortho = ortho.orthoTEI
	Norb = ortho.Norbs
	numAct = 2*numBathOrbs
	
	orthoOED_core1 = 2*np.dot(FBEorbs1[:,numAct:], FBEorbs1[:,numAct:].T) #+ 2*np.dot(entorbs, entorbs.T)
	orthoOED_core2 = reduce(np.dot, (FBEorbs2, np.diag(core_eigenvals), FBEorbs2.T))
	JKcore1 = np.einsum('pqrs,rs->pq', TEIortho, orthoOED_core1) - 0.5*np.einsum('prqs,rs->pq', TEIortho, orthoOED_core1)	
	JKcore2 = np.einsum('pqrs,rs->pq', TEIortho, orthoOED_core2) - 0.5*np.einsum('prqs,rs->pq', TEIortho, orthoOED_core2)
	
	Etest1 = 0.5* (orthoOED_core1 * (2*OEIortho + JKcore1)).sum()
	Etest2 = 0.5* (orthoOED_core2 * (2*OEIortho + JKcore2)).sum()


	JKdmet1 = reduce(np.dot,(FBEorbs1[:,:numAct].T, JKcore1, FBEorbs1[:,:numAct]))
	OEIdmet1 = reduce(np.dot,(FBEorbs1[:,:numAct].T, OEIortho, FBEorbs1[:,:numAct]))
	TEIdmet1 = ao2mo.incore.full(ao2mo.restore(8, TEIortho, Norb), FBEorbs1[:,:numAct], compact=False).reshape(numAct, numAct, numAct, numAct)
	
	JKdmet2 = reduce(np.dot,(FBEorbs2[:,:numAct].T, JKcore2, FBEorbs2[:,:numAct]))
	OEIdmet2 = reduce(np.dot,(FBEorbs2[:,:numAct].T, OEIortho, FBEorbs2[:,:numAct]))
	TEIdmet2 = ao2mo.incore.full(ao2mo.restore(8, TEIortho, Norb), FBEorbs2[:,:numAct], compact=False).reshape(numAct, numAct, numAct, numAct)	

	Nel, Nimp = 4, 2
	chempot= 0.0
	DMguess = None
	solver1 = qcsolvers.QCsolvers(OEIdmet1, TEIdmet1, JKdmet1, DMguess, numAct, Nel, Nimp, chempot)
	solver2 = qcsolvers.QCsolvers(OEIdmet2, TEIdmet2, JKdmet2, DMguess, numAct, Nel, Nimp, chempot)	
	Eimp1, Eemb1, OED1 = solver1.RHF()
	Eimp2, Eemb2, OED2 = solver2.RHF()
	assert np.isclose(Etest1 + Eemb1, mf.energy_elec()[0])
	assert np.isclose(Etest1, Etest2)
	assert np.isclose(Eimp1, Eimp2)	
	
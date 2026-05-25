const asyncHandler = require('express-async-handler');
const Complaint = require('../models/Complaint');

// @desc    Get user complaints
// @route   GET /api/complaints/my
// @access  Private (User)
const getMyComplaints = asyncHandler(async (req, res) => {
    // .select('-image') excludes the heavy base64 string from list view
    // .lean() returns plain JS objects instead of full Mongoose docs — much faster
    const complaints = await Complaint.find({ userId: req.user._id })
        .select('-image -aiDetections')
        .sort({ createdAt: -1 })
        .limit(50)
        .lean();

    res.status(200).json(complaints);
});

// @desc    Get officer complaints (by department)
// @route   GET /api/complaints/officer
// @access  Private (Officer)
const getOfficerComplaints = asyncHandler(async (req, res) => {
    if (!req.user.department) {
        res.status(400);
        throw new Error('Officer department not found');
    }

    // .lean() + exclude image for fast list rendering
    const complaints = await Complaint.find({ category: req.user.department })
        .select('-image -aiDetections')
        .populate('userId', 'name email phone city wardNumber')
        .sort({ createdAt: -1 })
        .limit(100)
        .lean();

    res.status(200).json(complaints);
});

// @desc    Create new complaint
// @route   POST /api/complaints
// @access  Private (User)
const createComplaint = asyncHandler(async (req, res) => {
    const { category, subCategory, description, location, image } = req.body;

    if (!category || !subCategory || !description || !location) {
        res.status(400);
        throw new Error('Please add all fields');
    }

    let aiCategory = '';
    let aiSeverity = '';
    let aiDetections = [];

    try {
        // Run text and image ML calls in PARALLEL — no sequential waiting
        const ML_BASE = process.env.ML_API_URL || 'http://127.0.0.1:8000';
        const mlPromises = [
            fetch(`${ML_BASE}/api/ml/analyze-text`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: description })
            }).then(r => r.ok ? r.json() : null).catch(() => null)
        ];

        if (image) {
            mlPromises.push(
                fetch(`${ML_BASE}/api/ml/analyze-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image })
                }).then(r => r.ok ? r.json() : null).catch(() => null)
            );
        }

        const [textData, imgData] = await Promise.all(mlPromises);

        if (textData) {
            aiCategory = textData.category || '';
            aiSeverity = textData.severity || '';
        }
        if (imgData) {
            aiDetections = imgData.detections || [];
        }
    } catch (error) {
        console.error('ML Integration Error:', error.message);
    }

    const complaint = await Complaint.create({
        userId: req.user.id,
        category,
        subCategory,
        description,
        location,
        image,
        aiCategory,
        aiSeverity,
        aiDetections
    });

    // Return without image to keep response lean
    const { image: _img, ...complaintData } = complaint.toObject();
    res.status(201).json({ msg: 'Complaint Created Successfully', complaint: complaintData });
});

// @desc    Get single complaint with image (for detail view)
// @route   GET /api/complaints/:id
// @access  Private (User or Officer)
const getComplaintById = asyncHandler(async (req, res) => {
    const isOfficer = req.user.role === 'officer';

    // Officers fetch by _id only (already authenticated — department check not needed here)
    // Citizens can only fetch their own complaints
    const query = isOfficer
        ? { _id: req.params.id }
        : { _id: req.params.id, userId: req.user._id };

    const complaint = await Complaint.findOne(query)
        .populate(isOfficer ? { path: 'userId', select: 'name email phone city wardNumber' } : null)
        .lean();

    if (!complaint) {
        res.status(404);
        throw new Error('Complaint not found');
    }

    res.status(200).json(complaint);
});

// @desc    Update complaint status (Assign, Resolve)
// @route   PUT /api/complaints/:id
// @access  Private (Officer)
const updateComplaint = asyncHandler(async (req, res) => {
    // findByIdAndUpdate is faster — single DB round-trip, no fetch-then-save
    const updatedComplaint = await Complaint.findByIdAndUpdate(
        req.params.id,
        req.body,
        { new: true, select: '-image -aiDetections' }
    ).lean();

    if (!updatedComplaint) {
        res.status(404);
        throw new Error('Complaint not found');
    }

    res.status(200).json(updatedComplaint);
});

module.exports = {
    getMyComplaints,
    getOfficerComplaints,
    createComplaint,
    getComplaintById,
    updateComplaint
};
